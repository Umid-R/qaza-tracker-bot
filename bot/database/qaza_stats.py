from supabase import create_client, Client
from dotenv import load_dotenv
import os
from datetime import  datetime, timedelta, time, date
import random
import logging



load_dotenv()


url=os.getenv("SUPABASE_URL")
key= os.getenv("SUPABASE_KEY")


Client = create_client(url, key)

def get_user_info(user_id: int):
    res = (
        Client
        .table("users")
        .select("id,name,lat,lon,joined,daily_goal", )
        .eq("id", user_id)
        .execute()
    )
    return res.data[0]


def get_all_users():
    res = (
        Client
        .table("users")
        .select("id,lat,lon")
        .execute()
    )

    return res.data

 

def get_total_qazas(user_id):
    res = (
        Client
        .table("qazas")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_qaza", True)
        .execute()
    )

    return res.count




def qazas_rating(user_id):
    res = (
        Client
        .table("qaza_counts")
        .select("prayer, counts")
        .eq("user_id", user_id)
        .execute()
    )

    
    breakdown = {
        "fajr": 0,
        "dhuhr": 0,
        "asr": 0,
        "maghrib": 0,
        "isha": 0
    }

    # Overwrite only existing prayers
    if res.data:
        for row in res.data:
            breakdown[row["prayer"]] = row["counts"]

    return breakdown




    

def get_prayers_stats(user_id: int):
    
    stats={}

    today = date.today()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)
    

    
    res = (
        Client
        .table("daily_prayers")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("prayer_date", today.isoformat())
        .execute()
    )

    stats['completed_today'] = res.count
    
    
    res = (
        Client
        .table("users")
        .select("daily_goal", count="exact")
        .eq("id", user_id)
        .execute())
    stats['daily_goal']=res.data[0]['daily_goal']
    
    
    today = date.today()
    start = datetime.combine(today - timedelta(days=6), time.min)
    end = datetime.combine(today, time.max)
    res = (
    Client
    .table("qazas")
    .select("id", count="exact")
    .eq("user_id", user_id)
    .eq("is_qaza", False)
    .gte("time_prayed", start.isoformat())
    .lte("time_prayed", end.isoformat())
    .execute())   
    stats["cleared_this_week"] = res.count
    
    
    res = (
    Client
    .table("qazas")
    .select("id", count="exact")
    .eq("user_id", user_id)
    .execute())
    stats["total_prayers_logged"] = res.count
    
    
    res = (
        Client
        .table("qazas")
        .select("time_prayed")
        .eq("user_id", user_id)
        .eq("is_qaza", False)
        .execute()
    )

    prayed_dates = {
        row["time_prayed"][:10]
        for row in res.data
        if row["time_prayed"]
    }

    streak = 0
    current_day = date.today()

    while current_day.isoformat() in prayed_dates:
        streak += 1
        current_day -= timedelta(days=1)
    
    stats['current_streak']=streak
    
    return stats

    
def get_weekly_activity(user_id: int):
    today = date.today()
    start_date = today - timedelta(days=6)
    
    try:
        # Fetch all prayers for last 7 days
        res = (
            Client
            .table("daily_prayers")
            .select("prayer_date")
            .eq("user_id", user_id)
            .gte("prayer_date", start_date.isoformat())
            .lte("prayer_date", today.isoformat())
            .execute()
        )
        data = res.data if res.data else []
    except Exception as e:
        logging.error(f"Failed to get weekly activity for {user_id}: {e}")
        data = []
    
    # Count prayers per day
    daily_counts = {}
    for row in data:
        prayer_date = row.get("prayer_date")
        if prayer_date:
            daily_counts[prayer_date] = daily_counts.get(prayer_date, 0) + 1
    
    # Build week status for last 7 days (oldest to newest)
    week_status = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        day_key = day.isoformat()
        
        week_status.append({
            "day": day.strftime("%a"),
            "status": daily_counts.get(day_key, 0) == 5
        })
    
    return week_status  



def get_profile_quote():
    res = (
        Client
        .table("profile_quotes")
        .select("quote")
        .execute()
    )
    quote=random.choice(res.data)
    return quote


def get_prayer_message(prayer):
    res = (
        Client
        .table("prayer_messages")
        .select("message")
        .eq('prayer',prayer)
        .execute()
    )
    message=random.choice(res.data)
    return message['message']


def get_prayer_times(user_id : int):
    res = (
        Client
        .table("prayer_times")
        .select("fajr,sunrise,dhuhr,asr,maghrib,isha,timezone")
        .eq("user_id", user_id)
        .execute()
    )
    
    return res.data[0]



def get_gif(type):
    res = (
        Client
        .table("gifs")
        .select("url")
        .eq("type", type)
        .execute()
    )
    
    return random.choice(res.data)['url']
    


def get_monthly_data(user_id: int, year: int, month: int):
    
    res = (
         Client
         .rpc(
            'get_monthly_prayer_data', 
            {
                'p_user_id': user_id,
                'p_year': year,
                'p_month': month
            }
        )
        .execute()
    )
    
    data = res.data 

    total_prayers = data['monthSummary']['adaPrayers'] + data['monthSummary']['missed']
    if total_prayers > 0:
        data['monthSummary']['completionRate'] = round(
            (data['monthSummary']['adaPrayers'] / total_prayers) * 100,
            2
        )
    else:
        data['monthSummary']['completionRate'] = 0
    
    return data
    
  





