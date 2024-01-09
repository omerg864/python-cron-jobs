from fastapi import FastAPI
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

load_dotenv()


app = FastAPI()

COUPONS_URL = os.getenv('COUPONS_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')
application = ApplicationBuilder().token(BOT_TOKEN).build()


async def check_users():
    ca = certifi.where()
    client = pymongo.MongoClient(os.environ.get("MONGODB_ACCESS"), tlsCAFile=ca)
    db = client.new_database
    chat_ids = db.registered.find()
    for chat_id in chat_ids:
        try:
            print(chat_id["_id"])
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



@app.get("/coupons")
async def coupons():
    await get_coupons()
    return {"message": "Success"}


@app.get("/movies")
async def movies():
    return {"message": "Hello World"}

@app.get("/fuel")
async def fuel():
    return {"message": "Hello World"}