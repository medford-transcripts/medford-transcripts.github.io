import time
import json, os
import glob
import ipdb

import folium
from folium.plugins import HeatMap
from geopy.geocoders import Nominatim
import osmnx as ox
import geopandas as gpd
from shapely.geometry import shape, Point

import utils
import datetime

def make_geojson():
    # from https://www.axisgis.com/MedfordMA
    wards = gpd.read_file("WARDSPRECINCTS2022_POLY.shp")


    # filter just medford wards
    wards = wards[wards['TOWN'] == 'MEDFORD'].copy()

    # reproject to EPSG:4326 coordinate system (expected by folium)
    wards = wards.to_crs(epsg=4326)

    # only save ward geometry
    wards = wards[['WARD', 'PRECINCT', 'geometry']] 

    # save file
    wards.to_file("medford_wards.geojson", driver="GeoJSON")

# Function to get latitude and longitude
def get_lat_lon(address):
    geolocator = Nominatim(user_agent="medfordTranscripts/1.0")
    try:
        location = geolocator.geocode(address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Error geocoding {address}: {e}")
    return None

def heatmap(addresses, labels=None, htmlname="heatmap.html",zoom_start=13.0, label_mode="tooltip", allow_none=False, return_wards_dict=True, skip_labels=False):

    # Get coordinates
    coordinates = []
    labels_aligned = []
    valid_addresses = []
    for i, address in enumerate(addresses):
        lat_lon = get_lat_lon(address)
        if lat_lon:
            coordinates.append(lat_lon)
            valid_addresses.append(address)
            if labels is not None and i < len(labels):
                labels_aligned.append(str(labels[i]))
            else:
                labels_aligned.append("")
        time.sleep(0.01)  # To avoid API rate limits

    if not coordinates:
        print("No valid coordinates found.")
        if not allow_none: return
        lat_lon = get_lat_lon("85 George P Hassett Dr, Medford, MA 02155")
        m = folium.Map(location=lat_lon, zoom_start=zoom_start)
    else:
        # Create a map centered at the first location
        m = folium.Map(location=coordinates[0], zoom_start=zoom_start)
        HeatMap(coordinates).add_to(m)

    # Optional: annotate each point
    if labels is not None and not skip_labels:
        for (lat, lon), text in zip(coordinates, labels_aligned):
            if not text:
                continue
            if label_mode == "tooltip":
                # Cleanest: small dot with hover text
                folium.CircleMarker(location=[lat, lon], radius=3, fill=True).add_to(m)
                folium.Marker(
                    location=[lat, lon],
                    tooltip=text,
                    icon=folium.Icon(icon="info-sign", prefix="glyphicon")
                ).add_to(m)
            else:  # "div" → always-visible text on the map
                folium.map.Marker(
                    [lat, lon],
                    icon=folium.DivIcon(
                        html=f"""<div style="font-size: 10pt; font-weight: 600; 
                                 text-shadow: 0 0 2px #fff; white-space: nowrap;">
                                 {html.escape(text)}</div>"""
                    )
                ).add_to(m)

    # Add ward boundaries
    with open("medford_wards.geojson", "r") as f:
        wards = json.load(f)

    folium.GeoJson(wards,
                    name="Wards",
                    style_function=lambda feature: {
                    "fillColor": "none",
                    "color": "black",
                    "weight": 2,
                    "dashArray": "5, 5"
                    },
                    tooltip=folium.GeoJsonTooltip(fields=["WARD"], aliases=["Ward:"])
                    ).add_to(m)

    ward_geoms = []

    # Add text labels for each wards
    for feature in wards["features"]:
        geom = shape(feature["geometry"])
        centroid = geom.centroid
        ward = str(feature["properties"].get("WARD", "")).strip()
        precinct = str(feature["properties"].get("PRECINCT", "")).strip()
        label = f"{ward}-{precinct}"

        folium.map.Marker(
            [centroid.y, centroid.x],
            icon=folium.DivIcon(
                html=f"""<div style="font-size: 12pt; font-weight: bold; white-space: nowrap;">{label}</div>"""
            )
        ).add_to(m)

        ward_geoms.append(
            {
                "geom": geom,
                "ward": ward,
                "precinct": precinct,
                "ward_precinct": label,
            }
        )

    # Add layer control
    folium.LayerControl().add_to(m)

    # Save to file
    m.save(htmlname)
    print("Heatmap saved as " + htmlname)
        

    # build Ward dictionary
    if return_wards_dict and coordinates:
        wards_dict = {}
        # labels_aligned and valid_addresses are aligned with coordinates
        for (lat, lon), name, addr in zip(coordinates, labels_aligned, valid_addresses):
            if not name:
                # if no label, skip; you can remove this if you want address-only keys
                continue

            pt = Point(lon, lat)
            ward_precinct = None

            for w in ward_geoms:
                if w["geom"].contains(pt):
                    ward_precinct = w["ward_precinct"]
                    break

            wards_dict[name] = {
                "address": addr,
                "ward": ward_precinct,
            }

        return wards_dict

    if return_wards_dict:
        # no coordinates, but user asked for dict
        return {}


def electeds_heatmap(position, year=None):

    if year is None: 
        # do all years
        outname = "election/" + position + '_heatmap.html'
    else:
        outname = "election/" + year + "_" + position + '_heatmap.html'


    #year = str(datetime.datetime.now().year)

    with open("councilors.json", 'r') as fp:
        directory = json.load(fp)

    addresses = []
    labels = []

    candidate_position = position.replace("_prelim","")

    for official in directory.keys():
        for this_year in directory[official].keys():
            if not this_year.isdigit() or len(this_year) != 4: continue
            if year is not None and this_year != year: continue

            if position in directory[official][this_year]["position"] or candidate_position in directory[official][this_year]["position"]:
                addresses.append(directory[official][this_year]["address"])

                if year is not None: labels.append(official + " " + this_year)
                else: labels.append(official)

    heatmap(addresses,labels=labels,htmlname=outname)

def speaker_heatmap():

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)

    addresses = []
    jsonfiles = glob.glob("20*/speaker_ids.json")
    for jsonfile in jsonfiles:
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)
        uniq_speakers = list({v for v in speaker_ids.values() if "SPEAKER_" not in v})
        for speaker in uniq_speakers:
            if speaker in directory.keys():
                if directory[speaker] != "":
                    addresses.append(directory[speaker])

    #ipdb.set_trace()
    heatmap(addresses,htmlname='speaker_appearance_heatmap.html')

def ward_list(wards_dict, skip_unknown=True):
    """
    wards_dict format:
    {
        "First Last": {"address": "...", "ward": "4-1"},
        ...
    }
    """

    def parse_ward(ward_str):
        """Convert '4-1' → (4,1). Handle None or ''."""
        if not ward_str:
            return (999, 999)  # put unassigned at end
        if "-" in ward_str:
            w, p = ward_str.split("-")
            return (int(w), int(p))
        return (int(ward_str), 0)

    def last_name(full_name):
        """Return last name for sorting."""
        return full_name.split()[-1]

    # Sort by ward, then last name
    sorted_items = sorted(
        wards_dict.items(),
        key=lambda item: (parse_ward(item[1]["ward"]), last_name(item[0]))
    )

    # Print nicely
    current_ward = None
    for name, data in sorted_items: 
        ward = data["ward"] or "Unknown"

        if skip_unknown and ward == "Unknown": continue

        if ward != current_ward:
            print(f"\n=== Ward {ward} ===")
            current_ward = ward

        print(f"{name:25s}  {data['address']}")

if __name__ == "__main__":


    with open("wards_dict.json", 'r') as fp:
        wards_dict = json.load(fp)
    ward_list(wards_dict, skip_unknown=False)
    ipdb.set_trace()


    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)
    addresses = list(directory.values())
    wards_dict = heatmap(addresses,labels=list(directory.keys()),skip_labels=True)

    # save the data
    with open("wards_dict.json", "w") as fp:
        json.dump(wards_dict, fp, indent=4)



    ipdb.set_trace()

    heatmap([],htmlname="wardmap.html",allow_none=True)
    ipdb.set_trace()

    positions = {
        "city_council_candidate":"City Council Candidates",
        "city_council_prelim_candidate":"City Council Prelim Candidates",
        "school_committee_candidate":"School Committee Candidates",
        "school_committee_prelim_candidate":"School Committee Prelim Candidates",
        "mayor_candidate": "Mayoral Candidates",
        "mayor_prelim_candidate": "Mayoral Prelim Candidates"

    }
    for position in positions.keys():
        electeds_heatmap(position=position)

    ipdb.set_trace()

    speaker_heatmap()

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)
    addresses = list(directory.values())
    heatmap(addresses)

    # quick test with just one address
    #addresses = [directory["Maryanne Adduci"]]
    #heatmap(addresses,htmlname='test.html')