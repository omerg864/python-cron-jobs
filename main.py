from fastapi import FastAPI, Request
import os
from bs4 import BeautifulSoup
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Updater, MessageHandler, filters
from dotenv import load_dotenv
import pymongo
import certifi
import time
import traceback
from PyPDF2 import PdfFileReader
import io

load_dotenv()


app = FastAPI()

COUPONS_URL = os.getenv('COUPONS_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')
application = ApplicationBuilder().token(BOT_TOKEN).build()

FUEL_ERROR_TEXT ="https://maintenance.gov.il/img/Bird-looking-and-standing-on-sign.png"


async def check_users():
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.new_database
    chat_ids = db.registered.find()
    for chat_id in chat_ids:
        try:
            await application.bot.send_message(chat_id=chat_id["_id"], text="Coupons")
        except Exception as e:
            print(e)
            db.registered.delete_many(chat_id)
            print("remove user")


async def coupon_scrape(url, start=False):
    try:
        response = requests.get(COUPONS_URL, headers={'User-Agent': 'Mozilla/5.0'}).text
        soup = BeautifulSoup(response, "html.parser")
        list_of_coupons = soup.find("div", {"class": "eq_grid pt5 rh-flex-eq-height col_wrap_three"})
        articles = list_of_coupons.find_all("article")
        first_name = articles[0].find("h3", {"class": "flowhidden mb10 fontnormal position-relative"})
        first_coupon_url = first_name.find("a")["href"]
        second_name = articles[1].find("h3", {"class": "flowhidden mb10 fontnormal position-relative"})
        second_coupon_url = second_name.find("a")["href"]
        urls2 = [first_coupon_url, second_coupon_url]
        new_coupons, urls = connect_to_db_coupons(urls2, True)
        print(urls2)
        if new_coupons:
            if start:
                await check_users()
            courses = []
            hit = False
            index = 0
            for article in articles:
                try:
                    name = article.find("h3", {"class": "flowhidden mb10 fontnormal position-relative"})
                    coupon_url = name.find("a")["href"]
                    if index != 0:
                        if coupon_url in urls:
                            hit = True
                            break
                    else:
                        if coupon_url == urls[0]:
                            hit = True
                            break
                    percent = article.find("span", {"class": "grid_onsale"}).text
                    if "100%" not in percent:
                        continue
                    image = article.find("img", {"class": "ezlazyload"})["data-ezsrc"]
                    time.sleep(4)
                    courses.append({"name": name.text, "url": coupon_url, "image": image, "percent": percent})
                except Exception as e:
                    print(e)
                    print("False coupon found")
                index += 1
            if index < 11:
                for course in courses:
                    await send_coupons(course["name"], course["percent"], course["url"], course["image"])
            else:
                await send_coupons_list(courses)
            return [new_coupons, hit, urls2]
    except Exception as e:
        print(e)
        print(traceback.format_exc())
        return False
    return [new_coupons]

async def get_coupons():
    ##"""Get the coupons from the website."""
    print("Checking coupons...")
    try:
        out = await coupon_scrape(COUPONS_URL, True)
        if out[0]:
            if not out[1]:
                print("page 2")
                await coupon_scrape(COUPONS_URL + 'page/2/')
            connect_to_db_coupons(out[2], False)
    except Exception as e:
        print(e)

def connect_to_db_coupons(urls, read):
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.new_database
    if not read:
        query = {"_id": 1}
        db.coupons.replace_one(query, {"url": urls[0], "url2": urls[1], "_id": 1})
    else:
        settings = db.coupons.find_one({"_id": 1})
        urls2 = [settings["url"], settings["url2"]]
        if urls[0] == urls2[0] or urls[1] == urls2[1]:
            print("No new coupons found")
            return [False, urls2]
        return [True, urls2]

async def send_coupons(name, percent, coupon_url, image):
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.new_database
    chat_ids = db.registered.find()
    for chat_id in chat_ids:
        is_waiting = db.waiting.find_one({"_id": chat_id['_id']})
        if is_waiting != None:
            db.gathered.insert_one({"chat_id": chat_id['_id'], "name": name, "coupon_url": coupon_url, "image": image, "percent": percent})
            print("Added to waiting list")
        else:
            print("sending coupon")
            await application.bot.sendPhoto(chat_id=chat_id["_id"], photo=image, caption=f'{name} is {percent}: {coupon_url}')
            print("sent coupon")

async def send_coupons_list(coupons):
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.new_database
    chat_ids = db.registered.find()
    message = ""
    index = 1
    for coupon in coupons:
        name = coupon["name"]
        percent = coupon["percent"]
        coupon_url = coupon["url"]
        message += f"{index}. {name} is {percent}: {coupon_url}\n"
    for chat_id in chat_ids:
        is_waiting = db.waiting.find_one({"_id": chat_id['_id']})
        if is_waiting != None:
            for coupon in coupons:
                db.gathered.insert_one({"chat_id": chat_id['_id'], "name": coupon['name'], "coupon_url": coupon['coupon_url'], "image": coupon['image'], "percent": coupon['percent']})
                print("Added to waiting list")
        else:
            await application.bot.send_message(chat_id=chat_id["_id"], text=message)
            print("sent coupons list")



def get_fuel_settings():
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.fuel
    fuel_settings = db.settings.find_one({"_id": 1})
    return fuel_settings["month"], fuel_settings["year"]

async def get_data_from_gov():
    print("Checking fuel costs...")
    months = ["jan", "feb", "march", "april", "may", "june", "july", "august", "sep", "october", "nov", "dec"]
    months_full = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    gov_url = "https://www.gov.il/BlobFolder/news/fuel-{month}-{year}/he/fuel-{index}-{year}.pdf"
    gov_alt_url = "https://www.gov.il/BlobFolder/news/fuel-{month}-{year}/he/{index}-{year}.pdf"
    month, year = get_fuel_settings()
    try:
        print(gov_url.format(month=months[month], year=f"{year}", index=f"{month + 1}"))
        response = requests.get(gov_url.format(month=months[month], year=f"{year}", index=f"{month + 1}"), headers={'User-Agent': 'Mozilla/5.0'})
        if FUEL_ERROR_TEXT not in response.text:
            print(response.content)
            print(FUEL_ERROR_TEXT not in response.text)
            await get_from_pdf(response, month, year)
        else:
            print(gov_url.format(month=months[month], year=f"{year}", index=f"{months[month]}"))
            response = requests.get(gov_url.format(month=months[month], year=f"{year}", index=f"{months[month]}"), headers={'User-Agent': 'Mozilla/5.0'})
            if FUEL_ERROR_TEXT not in response.text:
                await get_from_pdf(response, month, year)
            else:
                print(gov_alt_url.format(month=months[month], year=f"{year}", index=f"{month + 1}"))
                response = requests.get(gov_alt_url.format(month=months[month], year=f"{year}", index=f"{month + 1}"))
                if FUEL_ERROR_TEXT not in response.text:
                    await get_from_pdf(response, month, year)
                else:
                    print(gov_alt_url.format(month=months[month], year=f"{year}", index=f"{months[month]}"))
                    response = requests.get(
                        gov_alt_url.format(month=months[month], year=f"{year}", index=f"{months[month]}"))
                    if FUEL_ERROR_TEXT not in response.text:
                        await get_from_pdf(response, month, year)
                    else:
                        print(gov_url.format(month=months[month], year=f"{year}", index=f"{months_full[month]}"))
                        response = requests.get(
                            gov_url.format(month=months[month], year=f"{year}", index=f"{months_full[month]}"))
                        if FUEL_ERROR_TEXT not in response.text:
                            await get_from_pdf(response, month, year)
    except Exception as e:
        print(e)
        print("error")
        print(traceback.format_exc())


async def check_fuel_users():
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.fuel
    chat_ids = db.registered.find()
    for chat_id in chat_ids:
        try:
            await application.bot.send_message(chat_id=chat_id["_id"], text="Fuel")
        except Exception as e:
            print(e)
            db.registered.delete_many(chat_id)
            print("remove user")

async def get_from_pdf(response, month, year):
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.fuel
    registered = db.registered.find()
    await check_fuel_users()
    with io.BytesIO(response.content) as f:
        pdf = PdfFileReader(f)
        numpage = 1
        page = pdf.getPage(numpage)
        page_content = page.extractText()
        pc = page_content.split("\n")
        pc = list(filter(lambda a: a != "" and a != " ", pc))
        for i in range(len(pc)):
            if pc[i] == '-':
                pc[i + 1] = pc[i] + pc[i + 1]
        for i in range(pc.count("-")):
            pc.remove("-")
        pc = pc[-16:]
        if "-" in pc[3]:
            perc = pc[3].replace("-", "")
            price = pc[1] + " ₪ לליטר"
            message = f"מחיר הדלק הולך לרדת ב{perc} ויעמוד על {price}. כדאי לחכות לתדלק אחריי הירידה."
        else:
            price = pc[1] + " ₪"
            message = f"מחיר הדלק הולך לעלות ב{pc[3]} ויעמוד על {price}. כדאי לתדלק עכשיו."
        for user in registered:
            await application.bot.send_message(chat_id=user["_id"], text=message)
        update_fuel_settings(month, year)

def update_fuel_settings(month, year):
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.fuel
    query = {"_id": 1}
    if month == 11:
        month = 0
        year += 1
    else:
        month += 1
    db.settings.replace_one(query, {"_id": 1, "month": month, "year": year})


@app.get("/coupons")
async def coupons(request: Request):
    authorization = request.headers.get("Authorization")
    if authorization != os.getenv('AUTHORIZATION'):
        return {"error": "Unauthorized"}
    await get_coupons()
    return {"message": "Success"}


@app.get("/movies")
async def movies(request: Request):
    authorization = request.headers.get("Authorization")
    if authorization != os.getenv('AUTHORIZATION'):
        return {"error": "Unauthorized"}
    return {"message": "Hello World"}

@app.get("/fuel")
async def fuel(request: Request):
    authorization = request.headers.get("Authorization")
    if authorization != os.getenv('AUTHORIZATION'):
        return {"error": "Unauthorized"}
    await get_data_from_gov()
    return {"message": "Hello World"}