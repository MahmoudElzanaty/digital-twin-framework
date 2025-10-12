import requests
import json

# REPLACE WITH YOUR ACTUAL API KEY
API_KEY = "AIzaSyC2xAz-2BTBLIoXY9KDlEg57JDQjnj8ZS4"

def test_directions_api():
    """Test basic directions API call"""
    
    # Test route in Cairo: Tahrir Square to Cairo Tower
    origin = "30.0444,31.2357"  # Tahrir Square
    destination = "30.0459,31.2246"  # Cairo Tower
    
    url = f"https://maps.googleapis.com/maps/api/directions/json"
    
    params = {
        'origin': origin,
        'destination': destination,
        'mode': 'driving',
        'departure_time': 'now',  # Gets current traffic
        'key': API_KEY
    }
    
    print("Testing Google Maps Directions API...")
    print(f"Route: Tahrir Square → Cairo Tower")
    print(f"URL: {url}")
    print()
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if data['status'] == 'OK':
            route = data['routes'][0]['legs'][0]
            
            print("✅ API TEST SUCCESSFUL!")
            print()
            print(f"Distance: {route['distance']['text']}")
            print(f"Duration: {route['duration']['text']}")
            
            if 'duration_in_traffic' in route:
                print(f"Duration in traffic: {route['duration_in_traffic']['text']}")
                print(f"Traffic delay: {route['duration_in_traffic']['value'] - route['duration']['value']} seconds")
            
            print()
            print("Raw response:")
            print(json.dumps(data, indent=2)[:500] + "...")
            
            return True
        else:
            print(f"❌ API Error: {data['status']}")
            print(f"Message: {data.get('error_message', 'No error message')}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

if __name__ == "__main__":
    if API_KEY == "YOUR_API_KEY_HERE":
        print("⚠️  Please replace API_KEY with your actual Google Maps API key")
        print("Get it from: https://console.cloud.google.com/")
    else:
        test_directions_api()