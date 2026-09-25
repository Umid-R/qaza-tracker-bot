import requests

# Gets the cordinates of the city 
def get_cor_city(city):
    url = f"https://nominatim.openstreetmap.org/search?city={city}&format=json"
    response = requests.get(url,headers = {"User-Agent": "Mozilla/5.0 (TelegramBot)"})  
    data = response.json()
    if not data:
        return None
    lat = data[0]["lat"]
    lon = data[0]["lon"]
    return lat, lon

# Gets the prayer times for the specific cordinates
def get_by_cor(lat,lon):
  madhab = 1 #  1 = Hanafi 
  url = f"https://api.aladhan.com/v1/timings?latitude={lat}&longitude={lon}&method=2&school={madhab}"
  response = requests.get(url)
  response.raise_for_status()
  data = response.json()
  if not data:
        return None
  return (data['data']['timings'])




    
