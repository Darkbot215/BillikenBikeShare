from locale import format_string

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import json, base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import threading
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import services

load_dotenv("passwords.env")
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

services.load_settings()


def verificationInFuture(user_info):
    # This makes it so users with L or other holds are not removed from the list
    hold = user_info[4]
    if hold.strip() != "" and ("#" not in hold or "L" in hold):
        return True
    if len(user_info) == 7:
        temp = services.timeExtractor(user_info[6])
        now = services.now_local()
        if now > temp:
            return False
    return True

def dateExtractor(date):
    date_slash = [i for i, x in enumerate(date) if x == ('/')]
    date_dash = [i for i, x in enumerate(date) if x == ('-')]
    if len(date_slash) > 1:
        year = int(date[date_slash[1] + 1:])
        month = int(date[0:date_slash[0]])
        day = int(date[date_slash[0] + 1:date_slash[1]])

    elif len(date_dash) > 1:
        year = int(date[date_dash[1] + 1:])
        month = int(date[0:date_dash[0]])
        day = int(date[date_dash[0] + 1:date_dash[1]])
    else:
        # Send an error email
        return None
    if year < 2000:
        year = year + 2000
    try:
        temp = datetime(year, month, day, tzinfo=services.LOCAL_TZ)
        return temp.date()
    except:
        return None
        # Should email admins here


def duesExpired(user_info):
    raw_date = user_info[3].strip()
    if(raw_date == ""):
        return False
    temp = dateExtractor(raw_date)
    if temp is None:
        print(f"Error: Could not extract date from {raw_date}")
        return False  # If we can't read it, we assume NOT expired (or handle error)
    now = services.now_local().date()
    if now > temp:
        #date has passed
        return True
    return False


def experationUpdate(user_info):
    raw_date = user_info[2].strip()
    expo = dateExtractor(raw_date)
    if expo is None:
        print(f"Error: Could not extract date from {raw_date}")
        return False, None  # If we can't read it, we assume NOT expired (or handle error)
    raw_date = user_info[3].strip()
    if (raw_date == ""):
        return False, None
    dues = dateExtractor(raw_date)
    if dues is None:
        print(f"Error: Could not extract date from {raw_date}")
        return False, None  # If we can't read it, we assume NOT expired (or handle error)
    if dues > expo:
        return True, dues
    return False, None

def userExpired(user_info):
    print(user_info)
    raw_date = user_info[2].strip()
    expo = dateExtractor(raw_date)
    if expo is None:
        print(f"Error: Could not extract date from {raw_date}")
        return False  # If we can't read it, we assume NOT expired (or handle error)
    #This makes it so users with L or other holds are not removed from the list
    hold = user_info[4]
    if hold.strip() != "" and ("#" not in hold or "L" in hold):
        return False
    now = services.now_local()
    if now.date() > expo:
        return True
    return False

def deleteUsers(email_idxs, SPREADSHEET_ID, bike_sheet_dict):
    if(len(email_idxs) >=1):
        email_idxs.sort(reverse=True)
        requests = []
        for idx in email_idxs:
            # Since row_idx 1 = Row 2 of the sheet, idx IS the API index
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": bike_sheet_dict["UserLog"],
                        "dimension": "ROWS",
                        "startIndex": idx,
                        "endIndex": idx + 1
                    }
                }
            })
        sheet_service = services.get_sheets_service().spreadsheets()
        sheet_service.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': requests}
        ).execute()
def main():


    spreadsheet = services.get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    bike_sheet_dict = {}
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
        print(props["title"], props["sheetId"])

    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    markForDelete = []
    values = result.get("values", "")
    requests = []
    for row_idx, row in enumerate(values, start=1):
        # checks if user failed to be verified and cleans it up
        answer = verificationInFuture(row)
        if not answer:
            markForDelete.append(row_idx)
            continue
        # Checks and clears if dues have expired
        answer = duesExpired(row)
        if answer:
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["UserLog"],
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": 3,
                        "endColumnIndex": 4
                    },
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": ""}}]}],
                    "fields": "userEnteredValue"
                }
            })
            row[3] = ""
        # Checks if dues are longer than experiation date, then sets experiation date
        answer, new_date = experationUpdate(row)
        if answer:
            target = "UserLog!C" + str(row_idx + 1)
            expo_day = new_date.strftime("%m/%d/%Y")
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["UserLog"],
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": 2,
                        "endColumnIndex": 3
                    },
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": expo_day}}]}],
                    "fields": "userEnteredValue"
                }
            })
            row[2] = expo_day
        # Checks if the user has expired
        answer = userExpired(row)
        if answer:
            markForDelete.append(row_idx)
            continue
        # Checks if the user owes dues
        if row[3] == "" and int(row[1]) >= 1 and services.osSettings["paymentRequirement"]:
            hold = services.holdUpdate(row[4], holdToAdd="P", tempBanTime = services.osSettings["tempTimeout"])
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["UserLog"],
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": 4,
                        "endColumnIndex": 5
                    },
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": hold}}]}],
                    "fields": "userEnteredValue"
                }
            })
            row[4] = hold
        if "#" in row[4] and "P" in row[4] and row[3] != "":
            hold = services.holdUpdate(row[4], holdToRemove="P", tempBanTime = services.osSettings["tempTimeout"])
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["UserLog"],
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": 4,
                        "endColumnIndex": 5
                    },
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": hold}}]}],
                    "fields": "userEnteredValue"
                }
            })
            row[4] = hold
        if "#" in row[4]:
            cleaned_hold = services.holdUpdate(row[4], tempBanTime = services.osSettings["tempTimeout"])
            if cleaned_hold != row[4]:
                requests.append({
                    "updateCells": {
                        "range": {
                            "sheetId": bike_sheet_dict["UserLog"],
                            "startRowIndex": row_idx,
                            "endRowIndex": row_idx + 1,
                            "startColumnIndex": 4,
                            "endColumnIndex": 5
                        },
                        "rows": [{
                            "values": [
                                {"userEnteredValue": {"stringValue": cleaned_hold}}
                            ]
                        }],
                        "fields": "userEnteredValue"
                    }
                })
                row[4] = cleaned_hold
    if requests:
        services.get_sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

    deleteUsers(markForDelete, SPREADSHEET_ID, bike_sheet_dict)

if __name__ == "__main__":
    main()



