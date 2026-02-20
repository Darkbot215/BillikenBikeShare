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
                now = services.now_local()
                email_time = extension_code[7:]
                temp = services.timeExtractor(email_time)
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
                now = services.now_local()
                codeDict.update({"M": now})
            elif codeDict[item] < 255:
                codeDict[item] = codeDict[item] + 1
        else:
            if item == "M":
                now = services.now_local()
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



def main():
    SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
    services.load_settings()

    spreadsheet = services.get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    bike_sheet_dict = {}
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
        print(props["title"], props["sheetId"])

    RANGE_NAME = "Simple Bike Summary!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")

    norm_hours = services.osSettings["checkOutLength"]

    for row_idx, row in enumerate(values, start=1):
        #If we are checked out then we do this work
        if len(row) < 6:
            continue
        if row[1] == "Checked-out":
            checked_out_time = services.timeExtractor(row[5])
            extension = False
            temp_norm_hours = norm_hours
            if len(row) >= 7:
                extension, hour_count = extensionChecker(row[6])
            if extension:
                if hour_count is not None:
                    temp_norm_hours += hour_count

            now = services.now_local()
            due = checked_out_time + timedelta(hours = temp_norm_hours)
            if now > due:
                #The bike is apparently due... We now need to check if there has been an email and send stuff
                extra_overdue = ""
                if len(row) >= 7:
                    if "M" in row[6]:
                        email_time = row[6][7:]
                        temp = services.timeExtractor(email_time)
                        if temp + timedelta(hours = 24) > now:
                            continue
                        else:
                            extra_overdue = "2"
                else:
                    row.append("")

                if len(services.siteResponse["Emails"]["Overdue"+extra_overdue]) == 2:
                    services.siteResponse["Emails"]["Overdue"+extra_overdue].append("")
                services.send_gmail(services.get_gmail_service(),row[4],services.siteResponse["Emails"]["Overdue"+extra_overdue][0],
                           services.siteResponse["Emails"]["Overdue"+extra_overdue][1] +
                           "<a href="+services.osSettings["PageUrl"]+"/?bike="+row[0]+">"+services.osSettings["PageUrl"]+"/?bike="+row[0]+"</a>"+
                           services.siteResponse["Emails"]["Overdue"+extra_overdue][2] + "This notification is for bike: <b>" + row[0]+"</b>")
                services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"],"Bike #"+row[0]+" is overdue for return",
                           "<p> This bike was checked out at: <br>"+row[5]+"</p><p> The user was:<br>"+row[4]+"</p> It is overdue and a notification was just sent to the user")
                update = extensionUpdate(row[6],"M")
                target = "Simple Bike Summary!G" + str(row_idx + 1)
                body = {'values': [[update]]}
                sheet = services.get_sheets_service().spreadsheets()
                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID, range=target,
                    valueInputOption="USER_ENTERED", body=body).execute()
                row[6] = update



if __name__ == "__main__":
    main()
