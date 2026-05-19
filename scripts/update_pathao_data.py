import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.settings import get_pathao_config
from src.services.pathao.client import PathaoClient


def update_pathao_data():
    client = PathaoClient(**get_pathao_config(required=True))
    print("Fetching cities...")
    cities, error = client.get_cities()
    if error:
        raise RuntimeError(error)
    
    full_map = {}
    
    for city in cities:
        c_id = city['city_id']
        c_name = city['city_name']
        print(f"Fetching zones for {c_name} (ID: {c_id})...")
        zones, zone_error = client.get_zones(c_id)
        if zone_error:
            raise RuntimeError(zone_error)
        
        full_map[c_name] = {
            "city_id": c_id,
            "zones": {}
        }
        
        for zone in zones:
            z_id = zone['zone_id']
            z_name = zone['zone_name']
            print(f"  Fetching areas for {z_name} (ID: {z_id})...")
            areas, area_error = client.get_areas(z_id)
            if area_error:
                raise RuntimeError(area_error)
            
            full_map[c_name]["zones"][z_name] = {
                "zone_id": z_id,
                "areas": areas
            }
            
    os.makedirs("resources", exist_ok=True)
    with open("resources/pathao_map.json", "w") as f:
        json.dump(full_map, f, indent=4)
        
    print("Pathao data update complete! Saved to resources/pathao_map.json")

if __name__ == "__main__":
    update_pathao_data()
