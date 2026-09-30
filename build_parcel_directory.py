"""Build the private address -> owner-name candidate set from MassGIS parcels.

PURPOSE, narrowly. plan.txt 12.12 measured that identifying a speaker from a
self-introduction only works against a CLOSED candidate set, and that the set
was empty for members of the public: a one-off speaker is in no roster, so the
raw ASR spelling is all we have and it cannot be checked. This supplies the
missing set, indexed by ADDRESS, because a house number plus a street resolves
to one or two people while a name alone against a city resolves to noise --
measured 0.0% wrong at 2 candidates against 29.6% at 1,229.

WHAT THIS IS NOT FOR. It never supplies a name nobody gave. A speaker must have
stated their name aloud on the public record; this only repairs the spelling of
what they said, and disagreement is surfaced rather than silently resolved.

PRIVACY. Output is gitignored (street_list*.json, see .gitignore) and is the
same class as addresses.json, which has been excluded from the repo since it was
created. This module prints AGGREGATES ONLY -- never a name or an address --
because a session log is not a place for a resident directory either.

SOURCE. MassGIS Standardized Assessors' Parcels, Level 3, published per
municipality and refreshed each January 1 and July 1:
  download.massgis.digital.mass.gov/shapefiles/l3parcels/L3_SHP_M176_MEDFORD.zip
Bulk and official, so no municipal server is scraped. Medford is M176.

KNOWN LIMITATION, stated because it decides how the output may be used: parcels
record the OWNER, not the resident. Medford is roughly 40% renter-occupied, and
renters are disproportionately the people who speak at zoning and budget
hearings. Trusts and LLCs appear instead of people. So this covers the homeowner
half of the electorate and the street list -- a public record obtainable from the
Elections Commission -- is what covers the rest.

    python build_parcel_directory.py --zip <path> [--apply]
"""

import argparse
import collections
import io
import json
import os
import re
import struct
import sys
import zipfile

OUT = "street_list_parcels.json"

# Owner strings that are organisations, not residents.
ENTITY = re.compile(r"\b(LLC|L\.L\.C|INC|CORP|TRUST|TR\b|REALTY|ASSOC|PARTNERS|LP\b|"
                    r"CITY OF|TOWN OF|COMMONWEALTH|CHURCH|BANK|HOLDINGS|PROPERTIES|"
                    r"MANAGEMENT|ENTERPRISES|FOUNDATION|AUTHORITY|SCHOOL|HOSPITAL)\b",
                    re.I)

# Residential use codes: 101 single family, 102 condo, 103 mobile, 104 two-family,
# 105 three-family, 109/111-125 multi-family and apartments, 013 mixed with resid.
RESIDENTIAL = re.compile(r"^(0?1[0-9]{2}|013)")

STREET_TYPE = (r"(street|st|road|rd|avenue|ave|lane|ln|drive|dr|place|pl|terrace|ter|"
               r"way|circle|cir|court|ct|park|hill|square|sq|boulevard|blvd|row|path)")
ADDR_SPLIT = re.compile(r"^\s*(\d+[A-Za-z]?)\s+(.+?)\s*$")


def dbf_fields(fp):
    fp.seek(0)
    head = fp.read(32)
    nrec, hlen, rlen = struct.unpack("<I H H", head[4:12])
    flds, pos = [], 1
    fp.seek(32)
    while True:
        raw = fp.read(32)
        if not raw or raw[0:1] in (b"\r", b"\x00"):
            break
        name = raw[0:11].split(b"\x00")[0].decode("latin-1").strip()
        flds.append((name, raw[11:12].decode("latin-1"), pos, raw[16]))
        pos += raw[16]
    return nrec, hlen, rlen, flds


def dbf_rows(path, want):
    with open(path, "rb") as fp:
        nrec, hlen, rlen, flds = dbf_fields(fp)
        idx = {n: (p, l) for n, _t, p, l in flds}
        keep = [n for n in want if n in idx]
        fp.seek(hlen)
        for _ in range(nrec):
            rec = fp.read(rlen)
            if len(rec) < rlen or rec[0:1] == b"*":
                continue
            yield {n: rec[idx[n][0]:idx[n][0] + idx[n][1]].decode("latin-1").strip()
                   for n in keep}


def normalise_owner(raw):
    """Assessor owners are 'LAST FIRST M' or 'LAST FIRST & SPOUSE'. -> ['First Last'].

    Returns a LIST because a parcel commonly records two owners, and both are
    legitimate candidates for a speaker at that address.
    """
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s or ENTITY.search(s):
        return []
    s = re.sub(r"\b(JR|SR|II|III|IV|ET AL|ETAL|TRUSTEE|TRUSTEES|LIFE ESTATE|LE)\b\.?",
               " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,&")
    out = []
    # "SMITH JOHN & JANE"  ->  John Smith, Jane Smith
    m = re.match(r"^([A-Za-z'\-]+)\s+([A-Za-z'\-]+)(?:\s+[A-Z])?\s*&\s*([A-Za-z'\-]+)$", s)
    if m:
        last, first_a, first_b = m.group(1), m.group(2), m.group(3)
        return [("%s %s" % (first_a, last)).title(), ("%s %s" % (first_b, last)).title()]
    parts = s.split()
    if len(parts) < 2:
        return []
    last, first = parts[0], parts[1]
    if len(first) <= 1:
        return []
    out.append(("%s %s" % (first, last)).title())
    return out


def build(zip_path):
    tmp = os.path.join(os.path.dirname(os.path.abspath(zip_path)), "_parcels_tmp")
    z = zipfile.ZipFile(zip_path)
    target = [n for n in z.namelist() if n.endswith("Assess_CY26_FY26.dbf")]
    if not target:
        target = [n for n in z.namelist() if re.search(r"Assess.*\.dbf$", n)]
    if not target:
        raise SystemExit("no assessor .dbf in %s" % zip_path)
    z.extract(target[0], tmp)
    dbf = os.path.join(tmp, target[0])

    want = ["OWNER1", "SITE_ADDR", "USE_CODE", "OWN_CITY", "CITY"]
    stats = collections.Counter()
    by_addr = collections.defaultdict(set)
    by_building = collections.defaultdict(set)
    streets = collections.Counter()
    for r in dbf_rows(dbf, want):
        stats["parcels"] += 1
        if not RESIDENTIAL.match(r.get("USE_CODE") or ""):
            stats["skipped_non_residential"] += 1
            continue
        stats["residential"] += 1
        names = normalise_owner(r.get("OWNER1"))
        if not names:
            stats["owner_is_entity_or_unparseable"] += 1
            continue
        addr = re.sub(r"\s+", " ", (r.get("SITE_ADDR") or "")).strip().upper()
        m = ADDR_SPLIT.match(addr)
        if not m:
            stats["address_unparseable"] += 1
            continue
        num, rest = m.group(1), m.group(2)
        # STRIP THE UNIT, AND KEEP BOTH INDEXES.
        #
        # SITE_ADDR carries the unit ("MAIN ST 4B"), which made 2,548 of 3,201
        # "street names" unit numbers and wrecked the street list that mangled
        # street names have to be matched against. But stripping it is not free:
        # a speaker says "123 Main Street" with no unit, so the set they resolve
        # against is the whole BUILDING. For a 20-unit condo that genuinely is 20
        # candidates, and pretending otherwise would be a false precision.
        #   by_address  full address incl. unit -> 1.07 names, for exact lookups
        #   by_building number + street        -> what a spoken address matches
        street = re.sub(r"\s+(?:APT|UNIT|STE|FL|BLDG|REAR|#)\b.*$", "", rest, flags=re.I)
        street = re.sub(r"\s+\d+[A-Za-z]?$", "", street)          # trailing unit
        street = re.sub(r"\s+[A-Za-z]$", "", street) if re.search(
            r"\s\d", street) else street
        street = re.sub(r"\s+", " ", street).strip()
        if not street:
            stats["address_unparseable"] += 1
            continue
        streets[street] += 1
        key = "%s %s" % (num, rest)
        before = len(by_addr[key])
        by_addr[key].update(names)
        stats["names_added"] += len(by_addr[key]) - before
        by_building["%s %s" % (num, street)].update(names)
        # OWN_CITY outside Medford means the owner lives elsewhere: a landlord,
        # so they are a WEAKER candidate for someone speaking as a resident.
        if not (r.get("OWN_CITY") or "").upper().startswith("MEDFORD"):
            stats["owner_mailing_outside_medford"] += 1
    return stats, by_addr, by_building, streets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--apply", action="store_true", help="write %s" % OUT)
    args = ap.parse_args()

    stats, by_addr, by_building, streets = build(args.zip)
    print("AGGREGATES ONLY -- no name or address is printed by this tool.")
    print()
    for k in ("parcels", "residential", "skipped_non_residential",
              "owner_is_entity_or_unparseable", "address_unparseable",
              "owner_mailing_outside_medford"):
        print("  %-34s %s" % (k, format(stats[k], ",")))
    print()
    print("  %-34s %s" % ("distinct addresses", format(len(by_addr), ",")))
    print("  %-34s %s" % ("distinct street names", format(len(streets), ",")))
    bsizes = collections.Counter(len(v) for v in by_building.values())
    print("  %-34s %s" % ("distinct buildings (num+street)", format(len(by_building), ",")))
    bmed = sorted(len(v) for v in by_building.values())
    if bmed:
        print("  %-34s %.2f" % ("mean candidates per BUILDING",
                                sum(bmed) / float(len(bmed))))
        print("  %-34s %s" % ("buildings with 1-2 candidates",
                              format(bsizes[1] + bsizes[2], ",")))
        print("  %-34s %s" % ("buildings with 10+ candidates",
                              format(sum(n for k, n in bsizes.items() if k >= 10), ",")))
    sizes = collections.Counter(len(v) for v in by_addr.values())
    print("  %-34s %s" % ("addresses with 1 candidate name", format(sizes[1], ",")))
    print("  %-34s %s" % ("addresses with 2", format(sizes[2], ",")))
    print("  %-34s %s" % ("addresses with 3+",
                          format(sum(n for k, n in sizes.items() if k >= 3), ",")))
    med = sorted(len(v) for v in by_addr.values())
    if med:
        print("  %-34s %.2f" % ("mean candidates per address",
                                sum(med) / float(len(med))))
    if not args.apply:
        print()
        print("DRY RUN -- %s not written. Re-run with --apply." % OUT)
        return 0

    payload = {
        "_comment": ["Private address -> owner-name candidate set. GITIGNORED.",
                     "Purpose: repair the SPELLING of a name a speaker stated aloud",
                     "on the public record. Never a source of names nobody gave.",
                     "Owners, not residents: misses renters (~40% of Medford)."],
        "source": "MassGIS L3 Standardized Assessors' Parcels, M176 Medford, CY26/FY26",
        "built": __import__("datetime").date.today().isoformat(),
        "streets": sorted(streets),
        "by_address": {k: sorted(v) for k, v in sorted(by_addr.items())},
        "by_building": {k: sorted(v) for k, v in sorted(by_building.items())},
    }
    with io.open(OUT, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=1, ensure_ascii=False)
    print()
    print("wrote %s (%s bytes)" % (OUT, format(os.path.getsize(OUT), ",")))
    print("VERIFY IT IS IGNORED: git check-ignore -v %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
