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

#Main things to be done:
#Check if user has failed to verify by verification time
#Check if their dues have expired (need to be smart in checking text)
#Check if user has checked out at least one bike and not paid dues
#Check if dues is longer than expiration, and then update that
#Check if user has expired.

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

load_dotenv("passwords.env")

def get_credentials():
    service_account_info = json.loads(base64.b64decode(os.environ["GOOGLE_CREDS_BASE64"]))
    all_scopes = list(set(DRIVE_SCOPES + SHEETS_SCOPES))
    drive_creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=all_scopes
    )
    gmail_creds = Credentials(
        token=None,
        refresh_token= os.environ["EMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["EMAIL_CLIENT_ID"],
        client_secret=os.environ["EMAIL_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return {"drive":drive_creds,"gmail":gmail_creds}

creds = get_credentials()


def get_sheets_service():
    return build("sheets", "v4", credentials=creds["drive"])
def get_gmail_service():
    return build("gmail", "v1", credentials=creds["gmail"])

LOCAL_TZ = ZoneInfo("America/Chicago")

def now_local():
    return datetime.now(LOCAL_TZ)

def timeExtractor(time):
    date_indices = [i for i, x in enumerate(time) if x == ('/')]
    time_indices = [i for i, x in enumerate(time) if x == (':')]
    year = int(time[date_indices[1] + 1:date_indices[1] + 5])
    month = int(time[0:date_indices[0]])
    day = int(time[date_indices[0] + 1:date_indices[1]])
    hour = int(time[time_indices[0] - 2:time_indices[0]])
    minute = int(time[time_indices[0] + 1:time_indices[1]])
    second = int(time[time_indices[1] + 1:time_indices[1] + 3])
    temp = datetime(year, month, day, hour, minute, second, tzinfo=LOCAL_TZ)
    return temp

def verificationInFuture(user_info):
    if len(user_info) == 7:
        temp = timeExtractor(user_info[6])
        now = now_local()
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
        temp = datetime(year, month, day, tzinfo=LOCAL_TZ)
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
    now = now_local().date()
    if now > temp:
        #date has passed
        return True
    return False

def holdUpdate(currentHold, holdToAdd = "", holdToRemove = "", tempBanTime = 30):
    codeDict = {}
    #Unpack the current dictionary
    if currentHold != "":
        if currentHold[0] == "#":
            code = currentHold[1:6]
            if "U" in code:
                position = code.index("U")
                amt_checked_out = int(code[position + 1], 16)
                codeDict.update({"U":amt_checked_out})
            options = ["T", "R"]
            for letter in options:
                if letter in code:
                    now = now_local()
                    hold_time = currentHold[7:]
                    temp = timeExtractor(hold_time)
                    if temp > now: #This tells it not to change the time
                        codeDict.update({letter: temp})
            options = ["L", "P"]
            for x in options:
                if x in code:
                    codeDict.update({x:1})
            # Remove all items we need to remove from the dictionary
            for item in codeDict.keys():
                if item in holdToRemove:
                    if item == "T" or item == "R":  # ignore T and R, the code already deals with them
                        pass
                    elif codeDict[item] > 0:
                        codeDict[item] = codeDict[item] - 1
        else: #I don't think we should be here? maybe email error code?
            return currentHold
    #Add all items we need to add
    for item in holdToAdd:
        if item in codeDict.keys():
            if item == "R": #currently 'recently' counts as 30 minutes and so does temp ban
                now = now_local()
                T_time = now + timedelta(minutes=tempBanTime)
                codeDict.update({"T": T_time})
                del codeDict["R"]
            elif codeDict[item] < 14:
                codeDict[item] = codeDict[item] + 1
        else:
            if item == "T" or item == "R":
                now = now_local()
                T_time = now + timedelta(minutes=tempBanTime)
                codeDict.update({item: T_time})
            else:
                codeDict.update({item: 1})

    codeString = ""
    timeString = ""
    for item in codeDict.keys():
        if item == "U" and codeDict[item] > 0:
            codeString = codeString+item+ f"{codeDict[item]:X}"
        elif item == "T" or item == "R":
            if timeString == "":
                timeString = codeDict[item].strftime("%m/%d/%Y %H:%M:%S")
                codeString = codeString+item
            else:
                codeString = codeString.replace("R","T")
                timeString = codeDict["T"].strftime("%m/%d/%Y %H:%M:%S")

        elif codeDict[item] > 0:
            codeString = codeString + item
    if codeString != "":
        if len(codeString) > 5:
            #Send an email maybe of the error
            return currentHold
        while len(codeString) < 6:
            codeString = codeString+" "

        return f"#{codeString:<6}{timeString}"
    return ""

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
    now = now_local()
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
        sheet_service = get_sheets_service().spreadsheets()
        sheet_service.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': requests}
        ).execute()
def main():

    SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

    spreadsheet = get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    bike_sheet_dict = {}
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
        print(props["title"], props["sheetId"])

    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
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
            print("here")
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
        if row[3] == "" and int(row[1]) >= 1:
            hold = holdUpdate(row[4], holdToAdd="P")
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
            hold = holdUpdate(row[4], holdToRemove="P")
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
            cleaned_hold = holdUpdate(row[4])
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
        get_sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

    deleteUsers(markForDelete, SPREADSHEET_ID, bike_sheet_dict)

if __name__ == "__main__":
    main()



