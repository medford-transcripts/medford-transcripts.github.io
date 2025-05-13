import folium
from folium.plugins import HeatMap
from geopy.geocoders import Nominatim
import time
import json, os
import osmnx as ox
import geopandas as gpd

# from https://www.axisgis.com/MedfordMA
#wards = gpd.read_file("WARDSPRECINCTS2022_POLY.shp")
#wards = wards[['WARD', 'geometry']] 
#wards.to_file("medford_wards.geojson", driver="GeoJSON")


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

def heatmap(addresses, htmlname="heatmap.html"):

    # Get coordinates
    coordinates = []
    for address in addresses:
        lat_lon = get_lat_lon(address)
        if lat_lon:
            coordinates.append(lat_lon)
        time.sleep(1)  # To avoid API rate limits

    # Create a map centered at the first location
    if coordinates:
        m = folium.Map(location=coordinates[0], zoom_start=10)

        # Add heatmap
        HeatMap(coordinates).add_to(m)

        show_boundary=False # doesn't work...
        if show_boundary:
            # download Medford boundaries
            geojson_path = "medford_boundary.geojson"
            if not os.path.exists(geojson_path):
                medford = ox.geocode_to_gdf("Medford, Massachusetts, USA")
                # Save as GeoJSON
                medford.to_file(geojson_path, driver="GeoJSON")

            # add medford boundaries to heatmap
            geojson_data = json.loads(geojson_path)
            folium.GeoJson(
                geojson_data,
                name="Medford Boundaries",
                style_function=lambda feature: {
                    "fillColor": "none",
                    "color": "blue",
                    "weight": 2
                }
            ).add_to(m)


        # Add ward boundaries
        folium.GeoJson("medford_wards.geojson",
                        name="Wards",
                        style_function=lambda feature: {
                        "fillColor": "none",
                        "color": "black",
                        "weight": 2,
                        "dashArray": "5, 5"
                        },
                        tooltip=folium.GeoJsonTooltip(fields=["WARD"], aliases=["Ward:"])
                        ).add_to(m)

        # Add layer control
        folium.LayerControl().add_to(m)

        # Save to file
        m.save(htmlname)
        print("Heatmap saved as " + htmlname)
    else:
        print("No valid coordinates found.")

if __name__ == "__main__":

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)
    addresses = list(directory.values())

    heatmap(addresses)