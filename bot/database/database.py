from supabase import create_client, Client
from dotenv import load_dotenv
import os
from timezonefinder import TimezoneFinder
from datetime import date, datetime
load_dotenv()


url=os.getenv("SUPABASE_URL")
key= os.getenv("SUPABASE_KEY")

Client = create_client(url, key)

tf = TimezoneFinder()

def get_timezone_from_latlon(lat: float, lon: float) -> str | None:
    return tf.timezone_at(lat=lat, lng=lon)

def insert_user(id,name,lat,lon):
    response = (
    Client.table("users")
    .insert({'id':id,'name':name,'lat':lat,'lon':lon})
    .execute())
    
    if not response.data:
        print("Error inserting user:", response.json())
        return None
    else:
        print("Success-Inserted user:", response.data)
        return 1
  
def insert_prayer_times(user_id,fajr,sunrise,dhuhr,asr,maghrib,isha):
    response_user = (
    Client.table("users")
    .select('lat','lon')
    .eq('id',user_id)
    .execute())
    
    timezone=get_timezone_from_latlon(response_user.data[0]['lat'],response_user.data[0]['lon'])
    print(timezone)
    
    response = (
    Client.table("prayer_times")
    .insert({"user_id":user_id,"fajr":fajr,"sunrise":sunrise,"dhuhr":dhuhr,"asr":asr,"maghrib":maghrib,"isha":isha,'timezone':timezone})
    .execute()) 
    if not response.data:
        print("Error inserting user:", response.json())
        return None
    else:
        print("Success-Inserted user:", response.data)
        return 1
 
def update_prayer_times(user_id,fajr,sunrise,dhuhr,asr,maghrib,isha):
    response_user = (
    Client.table("users")
    .select('lat','lon')
    .eq('id',user_id)
    .execute())
    
    timezone=get_timezone_from_latlon(response_user.data[0]['lat'],response_user.data[0]['lon'])
    print(timezone)
    
    response = (
    Client.table("prayer_times")
    .update({"fajr":fajr,"sunrise":sunrise,"dhuhr":dhuhr,"asr":asr,"maghrib":maghrib,"isha":isha,'timezone':timezone})
    .eq("user_id", user_id)
    .execute())
    return bool(response.data)

def update_user(id,name,lat,lon):
    response = (
    Client.table("users")
    .update({'name':name,'lat':lat,'lon':lon})
    .eq("id", id)
    .execute())
    return bool(response.data)
    
def is_user_exist(id):
    response = (
        Client.table("users")
        .select("id")
        .eq("id", id)  
        .execute()
    )
    if response.data:
        return True
    return False


def add_qaza(prayer, user_id, reason=None):
    today = date.today()
    
    # 1. Remove from daily_prayers if exists
    Client.table('daily_prayers').delete().eq('user_id', user_id).eq('prayer', prayer).eq('prayer_date', today).execute()
    
    # 2. Remove ONLY qazas added from ADA page today
    today_start = datetime.combine(today, datetime.min.time()).isoformat()
    today_end = datetime.combine(today, datetime.max.time()).isoformat()
    Client.table('qazas').delete()\
        .eq('user_id', user_id)\
        .eq('prayer', prayer)\
        .eq('source', 'ada_page')\
        .gte('time_created', today_start)\
        .lte('time_created', today_end)\
        .execute()
    
    # 3. Insert with source tracking
    response = Client.table('qazas').insert({
        'user_id': user_id,
        'prayer': prayer,
        'reason': reason,
        'source': 'ada_page'
    }).execute()
    
    return 1
    
def add_prayer(prayer, user_id):
    today = date.today()
    
    # 1. Remove from daily_prayers if exists
    Client.table('daily_prayers').delete().eq('user_id', user_id).eq('prayer', prayer).eq('prayer_date', today).execute()
    
    
    # 2. Remove ONLY qazas added from ADA page today (not bulk qazas!)
    today_start = datetime.combine(today, datetime.min.time()).isoformat()
    today_end = datetime.combine(today, datetime.max.time()).isoformat()
    Client.table('qazas').delete()\
        .eq('user_id', user_id)\
        .eq('prayer', prayer)\
        .eq('source', 'ada_page')\
        .gte('time_created', today_start)\
        .lte('time_created', today_end)\
        .execute()
    
    # 2. Insert into daily_prayers
    response = Client.table('daily_prayers').insert({
        'user_id': user_id,
        'prayer': prayer,
    }).execute()
    
    return 1

def add_bulk_qazas(user_id, fajr=0, dhuhr=0, asr=0, maghrib=0, isha=0):
    prayers_to_add = {
        'fajr': fajr,
        'dhuhr': dhuhr,
        'asr': asr,
        'maghrib': maghrib,
        'isha': isha
    }
    
    for prayer_name, count in prayers_to_add.items():
        if count > 0:
            qaza_entries = [
                {
                    'user_id': user_id,
                    'prayer': prayer_name,
                    'reason': None,
                    'source': 'bulk_add'  # ✅ Mark as bulk
                }
                for _ in range(count)
            ]
            
            if qaza_entries:
                Client.table('qazas').insert(qaza_entries).execute()
    
    return 1

def update_qaza(prayer, user_id):
    response = (
        Client.table('qazas')
        .select('id')
        .eq('user_id', user_id)
        .eq('prayer', prayer)
        .order('time_created', desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        return 0  

    prayer_id = response.data[0]['id']

    response = (
        Client.table('qazas')
        .update({
            'is_qaza': False,
            'time_prayed': 'now()'
        })
        .eq('id', prayer_id)
        .execute()
    )

    return 1




def mark_qazas_prayed(user_id, fajr=0, dhuhr=0, asr=0, maghrib=0, isha=0):
    
    prayers_to_clear = {
        'fajr': fajr,
        'dhuhr': dhuhr,
        'asr': asr,
        'maghrib': maghrib,
        'isha': isha
    }
    
    for prayer_name, count in prayers_to_clear.items():
        if count > 0:
            # Get the OLDEST qazas that are still unpaid (is_qaza = true)
            # Order by id ASC to get oldest first
            oldest_qazas = Client.table('qazas')\
                .select('id')\
                .eq('user_id', user_id)\
                .eq('prayer', prayer_name)\
                .eq('is_qaza', True)\
                .order('id', desc=False)\
                .limit(count)\
                .execute()
            
            # Extract the IDs
            qaza_ids = [qaza['id'] for qaza in oldest_qazas.data]
            
            # Update those specific qazas
            if qaza_ids:
                Client.table('qazas')\
                    .update({
                        'is_qaza': False,
                        'time_prayed': datetime.now().isoformat()
                    })\
                    .in_('id', qaza_ids)\
                    .execute()
    
    return 1