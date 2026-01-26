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
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]


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

siteResponse = {}
osSettings = {}
def load_settings(SPREADSHEET_ID):
    siteResponse.clear()
    RANGE_NAME = "SiteResponseMessages!A1:E"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    values = result.get("values", [])
    currentDic = ""

    for row in values:
        if row and row[0]:
            currentDic = row[0]
            siteResponse.setdefault(currentDic, {})
        if currentDic and len(row) > 1:
            siteResponse[currentDic].setdefault(row[1], [])
            for cell in row[2:]:
                siteResponse[currentDic][row[1]].append(cell)
    #This is for the OS settings page, this is a bit less automatic and more manual
    osSettings.clear()
    RANGE_NAME = "osSettings"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    values = result.get("values", "")
    osSettings["helmets"] = values[0][1:]
    osSettings["helmets"] = [int(x) for x in osSettings["helmets"]]

    print("helmets")
    print(osSettings["helmets"])
    osSettings["adminEmails"] = values[1][1:]
    osSettings["adminLoginSafety"] = int(values[2][1]) == 1
    osSettings["tempTimeout"] = int(values[3][1])
    osSettings["checkOutLength"] = int(values[4][1])
    osSettings["TempBan"] = int(values[5][1]) == 1
    osSettings["EmailChecking"] = int(values[6][1]) == 1
    osSettings["MaxBikes"] = int(values[7][1])
    osSettings["PageUrl"] = values[8][1]
    osSettings["blankResponses"] = values[9][1:]




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

def extensionChecker(hold_code):
    extension = False

    if hold_code == "":
        return extension, None

    if hold_code[0] == "#":
        code = hold_code[1:6]
        if "X" in code:
            position = code.index("X")
            hours_extended = int(code[position + 1:position+3], 16)
            extension = True
            return extension, hours_extended

    extension = False
    return extension, None

def extensionUpdate(extension_code, extensionToAdd = "", extensionToRemove = "", ):
    codeDict = {}
    #Unpack the current dictionary
    if extension_code != "":
        if extension_code[0] == "#":
            code = extension_code[1:6]
            if "X" in code:
                position = code.index("X")
                length_of_extension = int(code[position + 1:position+3], 16)
                codeDict.update({"X":length_of_extension})
            if "M" in code:
                now = now_local()
                email_time = extension_code[7:]
                temp = timeExtractor(email_time)
                codeDict.update({"M": temp})

            # Remove all items we need to remove from the dictionary
            for item in codeDict.keys():
                if item in "M":
                    pass
                elif item in extensionToRemove:
                    if codeDict[item] > 0:
                        codeDict[item] = codeDict[item] - 1
        else: #I don't think we should be here? maybe email error code?
            return extension_code
    #Add all items we need to add
    for item in extensionToAdd:
        if item in codeDict.keys():
            if item == "M":
                now = now_local()
                codeDict.update({"M": now})
            elif codeDict[item] < 255:
                codeDict[item] = codeDict[item] + 1
        else:
            if item == "M":
                now = now_local()
                codeDict.update({"M": now})
            else:
                codeDict.update({item: 1})

    codeString = ""
    timeString = ""
    for item in codeDict.keys():
        if item == "X" and codeDict[item] > 0:
            codeString = codeString+item+ f"{codeDict[item]:X}"
        elif item == "M":
            print(codeDict[item])
            timeString = codeDict[item].strftime("%m/%d/%Y %H:%M:%S")
            codeString = codeString+item


    if codeString != "":
        if len(codeString) > 5:
            #Send an email maybe of the error
            return extension_code
        while len(codeString) < 6:
            codeString = codeString+" "

        return f"#{codeString:<6}{timeString}"
    return ""

def send_gmail(service,to,subject,html_contents,attachments=None):
    if attachments is None:
        attachments = []
    elif isinstance(attachments, str):
        attachments = [attachments]
    if isinstance(to, (list, tuple, set)):
        to = ", ".join(to)
    # Root message
    msg = MIMEMultipart()
    msg["To"] = to
    msg["From"] = "me"
    msg["Subject"] = subject

    # HTML body
    msg.attach(MIMEText(html_contents, "html"))
    # Attachments
    for path in attachments:
        content_type, encoding = mimetypes.guess_type(path)
        if content_type is None:
            content_type = "application/octet-stream"

        main_type, sub_type = content_type.split("/", 1)

        with open(path, "rb") as f:
            part = MIMEBase(main_type, sub_type)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = path.split("/")[-1]
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        msg.attach(part)
    # Encode message
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    # Send
    service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()



def main():
    SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
    load_settings(SPREADSHEET_ID)

    spreadsheet = get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    bike_sheet_dict = {}
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
        print(props["title"], props["sheetId"])

    RANGE_NAME = "Simple Bike Summary!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")

    norm_hours = osSettings["checkOutLength"]

    for row_idx, row in enumerate(values, start=1):
        #If we are checked out then we do this work
        if len(row) < 6:
            continue
        if row[1] == "Checked-out":
            checked_out_time = timeExtractor(row[5])
            extension = False
            temp_norm_hours = norm_hours
            if len(row) >= 7:
                extension, hour_count = extensionChecker(row[6])
            if extension:
                if hour_count is not None:
                    temp_norm_hours += hour_count

            now = now_local()
            due = checked_out_time + timedelta(hours = temp_norm_hours)
            if now > due:
                #The bike is apparently due... We now need to check if there has been an email and send stuff
                extra_overdue = ""
                if len(row) >= 7:
                    if "M" in row[6]:
                        email_time = row[6][7:]
                        temp = timeExtractor(email_time)
                        if temp + timedelta(hours = 24) > now:
                            continue
                        else:
                            extra_overdue = "2"
                else:
                    row.append("")

                if len(siteResponse["Emails"]["Overdue"+extra_overdue]) == 2:
                    siteResponse["Emails"]["Overdue"+extra_overdue].append("")
                send_gmail(get_gmail_service(),row[4],siteResponse["Emails"]["Overdue"+extra_overdue][0],
                           siteResponse["Emails"]["Overdue"+extra_overdue][1] +
                           "<a href="+osSettings["PageUrl"]+"/?bike="+row[0]+">"+osSettings["PageUrl"]+"/?bike="+row[0]+"</a>"+
                           siteResponse["Emails"]["Overdue"+extra_overdue][2] + "This notification is for bike: <b>" + row[0]+"</b>")
                send_gmail(get_gmail_service(),osSettings["adminEmails"],"Bike #"+row[0]+" is overdue for return",
                           "<p> This bike was checked out at: <br>"+row[5]+"</p><p> The user was:<br>"+row[4]+"</p> It is overdue and a notification was just sent to the user")
                update = extensionUpdate(row[6],"M")
                target = "Simple Bike Summary!G" + str(row_idx + 1)
                body = {'values': [[update]]}
                sheet = get_sheets_service().spreadsheets()
                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID, range=target,
                    valueInputOption="USER_ENTERED", body=body).execute()
                row[6] = update



if __name__ == "__main__":
    main()
