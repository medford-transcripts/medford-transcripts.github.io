import time
import json, os
import glob
import ipdb

import folium
from folium.plugins import HeatMap
from geopy.geocoders import Nominatim
import osmnx as ox
import geopandas as gpd
from shapely.geometry import shape

import utils


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

def heatmap(addresses, htmlname="heatmap.html",zoom_start=5.0):

    # Get coordinates
    coordinates = []
    for address in addresses:
        lat_lon = get_lat_lon(address)
        if lat_lon:
            coordinates.append(lat_lon)
        time.sleep(0.01)  # To avoid API rate limits

    ipdb.set_trace()

    # Create a map centered at the first location
    if coordinates:
        m = folium.Map(location=coordinates[0], zoom_start=zoom_start)

        # Add heatmap
        HeatMap(coordinates).add_to(m)

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


        # Add layer control
        folium.LayerControl().add_to(m)

        # Save to file
        m.save(htmlname)
        print("Heatmap saved as " + htmlname)
    else:
        print("No valid coordinates found.")

def electeds_heatmap(school_committee=False, city_council=False, mayor=False, year=None, candidates=False, superintendents=False):

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)

    elected_addresses = []

    councilors = utils.get_councilors()
    for councilor in councilors:
        if councilor in directory.keys():
            elected_addresses.append(directory[councilor])

    heatmap(elected_addresses,htmlname='elected_heatmap.html')

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

if __name__ == "__main__":

    speaker_heatmap()
    ipdb.set_trace()

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)
    addresses = list(directory.values())
    heatmap(addresses)

    # quick test with just one address
    #addresses = [directory["Maryanne Adduci"]]
    #heatmap(addresses,htmlname='test.html')