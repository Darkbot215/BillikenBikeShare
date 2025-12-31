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
from random import randint
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from email_validator import validate_email, EmailNotValidError


#Set up google drive:
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
def get_drive_service():
    return build("drive", "v3", credentials=creds["drive"])
def get_gmail_service():
    return build("gmail", "v1", credentials=creds["gmail"])
# ------------------------------------
# GOOGLE DRIVE CLIENT
# ------------------------------------

SPREADSHEET_ID = "1o-r-D--evfEa3iHuViri5V3fb33a7iv_Op4IspKnO-0"


spreadsheet = get_sheets_service().spreadsheets().get(
    spreadsheetId=SPREADSHEET_ID
).execute()
bike_sheet_dict = {}
for sheet in spreadsheet["sheets"]:
    props = sheet["properties"]
    bike_sheet_dict.update({props["title"]: props["sheetId"]})
    print(props["title"], props["sheetId"])


app = Flask(__name__)
CORS(app)  # allows your HTML file to communicate with the server
#TEMP VARIABLES TO BE LOADED AS OS SETTINGS
helmetMax = 10


LOCAL_TZ = ZoneInfo("America/Chicago")

def now_local():
    return datetime.now(LOCAL_TZ)



siteResponse = {}
osSettings = {}
def load_settings():
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
    osSettings["tempTimeout"] = int(values[2][1])
    osSettings["TempBan"] = int(values[3][1]) == 1
    osSettings["EmailChecking"] = int(values[4][1]) == 1
    osSettings["MaxBikes"] = int(values[5][1])
    osSettings["PageUrl"] = values[6][1]



load_settings()
print(osSettings)

@app.route("/table", methods=["GET"])
def bike_table():
    RANGE_NAME = "Simple Bike Summary!A2:B"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    now = now_local()
    current_time = now.strftime("%I:%M %p")
    bikelist = []
    for row in values:
        if row[1] == "Checked-in":
            output_color = "#88E788"
        elif row[1] == "Checked-out":
            output_color = "#FF7F7F"
        else:
            output_color = "#FFAC1C"
        bikelist.append({"id": row[0], "status": row[1], "color": output_color})
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
        "topText": siteResponse["InitialPage"]["Table"][0],
        "textbox": siteResponse["InitialPage"]["Table"][1]
    })

@app.route("/status", methods=["POST"])
def bike_status():
    data = request.get_json()
    bikeid = int(data.get("bikeid", ""))
    # Do something with the text:
    RANGE_NAME = "Simple Bike Summary!A2:B"
    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    try:
        bike_ids = [int(row[0]) for row in values]
        print(bike_ids)
    except:
        pass
        #EMAIL ERROR CODE TO SLU EMAIL CONSIDER ADDING ADMINLIST
        #send_email("Error in bike_status function due to not all list items being integers. Check the bikeid list on the Bike Summary page to see if there are any non number bikeids", "erictmans@gmail.com","ERROR on BIKESHARE server")
    if bikeid in bike_ids:
        idx = bike_ids.index(bikeid)
    else:
        #That bike does not exist
        return (jsonify({
            "status": 2,
            "statusText": siteResponse["InitialPage"]["NotFound"][0],
            "text1": siteResponse["InitialPage"]["NotFound"][0]
        }))


    if values[idx][1] == "Checked-in":
        return jsonify({
            "status": 0,
            "text1": siteResponse["InitialPage"]["Checked-in"][1],
            "helmetList": osSettings["helmets"]
        })
    elif values[idx][1] == "Checked-out":
        return jsonify({
            "status":1,
            "text1": siteResponse["InitialPage"]["Checked-out"][1],
            "text2": siteResponse["InitialPage"]["Checked-out"][2],
            "helmetList": osSettings["helmets"]
        })
    else:
        RANGE_NAME = "Simple Bike Summary!D"+str(idx+2) #Plus 2 for the title row not read, and that excel starts at 1 not 0
        sheet = get_sheets_service().spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME
        ).execute()
        note = result.get("values", [[""]])[0][0]
        return jsonify({
            "status": 2,
            "statusText":"Unavailable",
            "text1": "<p><b>This bike's status is currently listed as:</b> <br>"+values[idx][1]+"</p> <b>Additional notes include:</b><br>"+note
        })

@app.route("/checkOut",methods=["POST"])
def checkOut():
    data = request.get_json()
    email = data.get("emailCheckOut", "")
    if not email:
      return jsonify({"error": "Email required"}), 400
    email = email.strip().lower()
    #Find if email is in list
    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    print(values)
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
        print('this user is on the list')
    else:
        #This email is not in user list. Now we need to do rigorous checking
        emailLegit = emailChecker(email)
        if emailLegit:
            print('this email is legit')
            addUser(email)
            return jsonify({
        "topText": siteResponse["Check-out"]["FirstTime"][0],
        "textbox": siteResponse["Check-out"]["FirstTime"][1]
    })

        else:
            return jsonify({
                "topText": siteResponse["Check-out"]["BadEmail"][0],
                "textbox": siteResponse["Check-out"]["BadEmail"][1]
            })
    #Now we are dealing with people in the user list! that is fun.
    #Main checks Are they verified, do they have a free ride - > have they paid ->
    user_info = values[email_idx]
    verification_time = user_info[6] if len(user_info) > 6 else None
    if verification_time:
        return jsonify({
            "topText": siteResponse["Check-out"]["NotYetVerified"][0],
            "textbox": siteResponse["Check-out"]["NotYetVerified"][1]
        })
    hold_status = user_info[4]
    if user_info[3] == "" and int(user_info[1]) >= 2:
        pass
        hold_status = holdUpdate(hold_status, holdToAdd = "P")
        #This is a scuffed dues based hold. A permanent one should be added
    hold, output = holdChecker(hold_status) #EDIT MAX AMOUNT OF BIKES CHECKED OUT
    if hold:
        return jsonify({
            "topText": output[0],
            "textbox": output[1]
        })

    #Congrats, they are good to check out a bike. Now we doublecheck the bike is good to check out and then send code
    RANGE_NAME = "Simple Bike Summary!A2:E"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike = int(data.get("bikeCheckOut", ""))
    helmet = data.get("helmetCheckOut", "")
    helmet = int(helmet)
    bike_list = [int(row[0]) for row in values]
    if bike in bike_list:
        bike_idx = bike_list.index(bike)
        if values[bike_idx][1] == "Checked-in": #shit, we made it, we can check out
            driveCheckout(user_info,email_idx,bike,bike_idx,helmet)
            message_body = (
                    "Thank you for using Billiken Bikeshare Program run by SLU on the Move!\n\n"
                    "Here is your unlock code for the bike:\n"
                    +str(values[bike_idx][2])+ "\n\n"
                    "Don't forget to check your bike back in within 24 hours by scanning the QR code! "
            )
            send_gmail(get_gmail_service(),email,"Billiken Bikeshare Unlock Code: " + str(values[bike_idx][2]),message_body)
            return jsonify({
                "topText": siteResponse["Check-out"]["Success"][0],
                "textbox": siteResponse["Check-out"]["Success"][1]
            })
        return jsonify({
                "topText": siteResponse["Check-out"]["Fail"][0],
                "textbox": siteResponse["Check-out"]["Fail"][1]
        })
    return jsonify({
        "topText": siteResponse["Check-out"]["Error14"][0],
        "textbox": siteResponse["Check-out"]["Error14"][1]
    })

@app.route("/checkIn",methods=["POST"])
def checkin():
    bike = request.form.get("bikeCheckIn")
    bike = int(bike)
    bciw = request.form.get("BikeCheckedInWrong", "false").lower() == "true"
    issues = request.form.get("mechanicalCheckIn")
    helmet = request.form.get("helmetCheckIn")
    helmet = int(helmet)

    photo = request.files.get("photo")  # may be None
    #Need to do 4 things
    #Email individual user about failed check-in?
    #hold option for user who failed to check in (default off)
    #Email sluonthemove about failed check-in
    RANGE_NAME = "Simple Bike Summary!A2:E"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike_list = [int(row[0]) for row in values]
    if bike in bike_list:
        bike_idx = bike_list.index(bike)
    else:
        return jsonify({
            "topText": siteResponse["Check-in"]["Error11"][0],
            "textbox": siteResponse["Check-in"]["Error11"][1]
        })
    email = values[bike_idx][-1]

    email = email.strip().lower()
    # Find if email is in list
    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    print(values)
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
        print('this user is on the list')
    else:
        return jsonify({
            "topText": siteResponse["Check-in"]["Error12"][0],
            "textbox": siteResponse["Check-in"]["Error12"][1]
        })
        #Also a shitty error
    user_list = values
    photo_path = ""
    try:
        if photo:
            filename = photo.filename
            photo_path = f"/tmp/{filename}"
            photo.save(photo_path)  # or wherever
    except Exception as e:
        print("Error in checkout_async:", e)

    threading.Thread(
        target=checkin_async,
        args=(
            bike, bciw, issues, helmet, photo_path, email,
            user_list, email_idx, bike_idx
        ),
        daemon=False
    ).start()

    return jsonify({
        "topText": siteResponse["Check-in"]["Success"][0],
        "textbox": siteResponse["Check-in"]["Success"][1]
    })


@app.route("/submitVerify",methods=["POST"])
def verifyUser():
    data = request.get_json()
    email = data.get("email", "")
    email = email.strip().lower()
    verificationCode = data.get("verificationCode","")
    newCode = data.get("newCode",[])
    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    print(values)
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return jsonify({
        "topText": siteResponse["VerifyUser"]["NotInSystem"][0],
        "textbox": siteResponse["VerifyUser"]["NotInSystem"][1]
    })
    user_info = values[email_idx]
    now = now_local()
    try:
        ver_time = user_info[6]
    except:
        return jsonify({
        "topText": siteResponse["VerifyUser"]["AlreadyDone"][0],
        "textbox": siteResponse["VerifyUser"]["AlreadyDone"][1]
    })
    print(newCode)
    if newCode:
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "dimension": "ROWS",
                    "startIndex": email_idx + 1,
                    "endIndex": email_idx + 2
                },
            }
        }]
        sheet.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': [requests]}
        ).execute()
        addUser(email)
        return jsonify({
            "topText": siteResponse["VerifyUser"]["NewCode"][0],
            "textbox": siteResponse["VerifyUser"]["NewCode"][1]
        })

    temp = timeExtractor(ver_time)

    if temp >= now:
        #We are within time.
        if str(user_info[5]) == str(verificationCode.strip()):
        #Success. This account can be verified
            print(email_idx+2)
            sheet.values().clear(
                spreadsheetId=SPREADSHEET_ID,
                range="UserLog!G"+str(email_idx+2)
            ).execute()

            return jsonify({
                "topText": siteResponse["VerifyUser"]["Success"][0],
                "textbox": siteResponse["VerifyUser"]["Success"][1]
            })
        else:
            return jsonify({
                "topText": siteResponse["VerifyUser"]["Wrong"][0],
                "textbox": siteResponse["VerifyUser"]["Wrong"][1]
            })
    else:
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "dimension": "ROWS",
                    "startIndex": email_idx+1,
                    "endIndex": email_idx+2
                },
            }
        }]
        sheet.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': [requests]}
        ).execute()
        addUser(email)
        return jsonify({
            "topText": siteResponse["VerifyUser"]["TooSlow"][0],
            "textbox": siteResponse["VerifyUser"]["TooSlow"][1]
        })

def addUser(email):
    now = now_local()
    sheet = get_sheets_service().spreadsheets()
    epoch = date(1899, 12, 30)
    today = date.today()
    account_expiration = date(today.year + (today.month > 5), 5, 31)
    serial_date = (account_expiration - epoch).days
    code_expiration = now + timedelta(minutes=30)
    verification_code = randint(100000, 999999)
    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 2
                },
                "inheritFromBefore": False
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 7
                },
                "rows": [
                    {
                        "values": [
                            {"userEnteredValue": {"stringValue": email}},
                            {"userEnteredValue": {"numberValue": 0}},
                            {
                                "userEnteredValue": {
                                    "numberValue": serial_date

                                },
                                "userEnteredFormat": {
                                    "numberFormat": {
                                        "type": "DATE",
                                        "pattern": "MM/dd/YYYY"
                                    }
                                }
                            },
                            {},{},  # intentionally empty
                            {"userEnteredValue": {"numberValue": verification_code}},
                            {"userEnteredValue": {"stringValue": code_expiration.strftime("%m/%d/%Y %H:%M:%S")}}
                        ]
                    }
                ],
                "fields": "userEnteredValue,userEnteredFormat"
            }
        }
    ]
    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={'requests': [requests]}
    ).execute()

    message_body = (
            "Welcome to the Billiken Bikeshare Program run by SLU on the Move!\n\n"
            "To verify your email for bikeshare use click the link below\n"
            "https://your-site.com/verify?email=" + email + "&code=" + str(verification_code) + "\n\n"
                                                                                                "Or enter your code and email on this webpage:https://your-site.com/verify "
    )
    send_gmail(get_gmail_service(),email,"Billiken Bikeshare Verification Code: " + str(verification_code),message_body)

def emailChecker(email,on = osSettings["EmailChecking"]):
    period = False
    emailLegit = False
    try:
        validate_email(email)
    except EmailNotValidError:
        return False
    for i in range(len(email)):
        if email[i] == ".":
            period = True
        if email[i] == "@":
            ending = email[len(email) - 7:]  # This is the 7 characters of slu.edu
            if ending == "slu.edu":
                if period:
                    emailLegit = True
                break
            break
    return emailLegit or not on

def holdChecker(hold_code, max_amount = osSettings["MaxBikes"], tempBan = osSettings["TempBan"]):
    hold = False
    topText = ""
    textbox = ""
    if hold_code == "":
        return hold, [topText, textbox]

    if hold_code[0] == "#":
        code = hold_code[1:6]
        if "T" in code:
            now = now_local()
            hold_time = hold_code[7:]
            temp = timeExtractor(hold_time)
            if temp > now:
                hold = tempBan
                topText = siteResponse["Check-out"]["Fail"][0]
                textbox = siteResponse["Check-out"]["Fail"][1]+" You must wait " + str(int((temp - now).seconds / 60) + 1) + " minutes to check out a new bike"
            # Could add an else here to delete it, but that is a later problem
        if "U" in code:
            position = code.index("U")
            amt_checked_out = int(code[position + 1], 16)
            if amt_checked_out >= max_amount:
                hold = True
                topText = siteResponse["Check-out"]["U-hold"][0]
                textbox = siteResponse["Check-out"]["U-hold"][1]+" ("+str(max_amount)+") "+siteResponse["Check-out"]["U-hold"][2]+" You currently have "+code[position + 1] +" bike checked out"
        if "P" in code:
            hold = True
            topText = siteResponse["Check-out"]["P-hold"][0]
            textbox = siteResponse["Check-out"]["P-hold"][1]
        if "L" in code:
            hold = True
            topText = siteResponse["Check-out"]["L-hold"][0]
            textbox = siteResponse["Check-out"]["L-hold"][1]


    else: #This is if they have a manually added hold on the account
        hold = True
        topText = siteResponse["Check-out"]["Other-hold"][0]
        textbox = siteResponse["Check-out"]["Other-hold"][1]


    return hold, [topText, textbox]

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

def driveCheckout(user_info,email_idx, bikeid, bike_idx, helmetid):
    sheet = get_sheets_service().spreadsheets()
    #4 Updates to be done
    #Update userlog with times checked out and new hold on account
    #Update bike summary with checked-out
    #Update bike specific log (add a row)
    #Update helmet log
    hold = user_info[4]
    hold = holdUpdate(hold, "RU")
    now = now_local()

    requests = [

        # Update user log: +1 ride, update hold
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "startRowIndex": email_idx + 1,
                    "endRowIndex": email_idx + 2,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2  # ONLY the rides column
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"numberValue": int(user_info[1]) + 1}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "startRowIndex": email_idx + 1,
                    "endRowIndex": email_idx + 2,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5  # ONLY the hold column
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": hold}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "startRowIndex": bike_idx + 1,
                    "endRowIndex": bike_idx + 2,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2  # status column only
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": "Checked-out"}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "startRowIndex": bike_idx + 1,
                    "endRowIndex": bike_idx + 2,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5  # last-user column only
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": user_info[0]}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },

        # Insert new row in individual bike log
        {
            "insertDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["Bike" + str(bikeid)],
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 2
                },
                "inheritFromBefore": False
            }
        },

        # Update individual bike log
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Bike" + str(bikeid)],
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}},
                        {"userEnteredValue": {"stringValue": user_info[0]}},
                        {"userEnteredValue": {"stringValue": "Checked-out"}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        }
    ]
    if helmetid != -1:
        requests.extend([
            # Insert new row in helmet log
            {
                "insertDimension": {
                    "range": {
                        "sheetId": bike_sheet_dict["HelmetLog"],
                        "dimension": "ROWS",
                        "startIndex": 1,
                        "endIndex": 2
                    },
                    "inheritFromBefore": False
                }
            },

            # Update helmet log
            {
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["HelmetLog"],
                        "startRowIndex": 1,
                        "endRowIndex": 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4
                    },
                    "rows": [{
                        "values": [
                            {"userEnteredValue": {"numberValue": helmetid}},
                            {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}},
                            {"userEnteredValue": {"stringValue": user_info[0]}},
                            {"userEnteredValue": {"stringValue": "Checked-out"}}
                        ]
                    }],
                    "fields": "userEnteredValue"
                }
            }
        ])

    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={'requests': [requests]}
    ).execute()
    
def driveCheckin(user_info,email_idx, bikeid, bike_idx, helmetid, notes, hold_long_term = False):
    sheet = get_sheets_service().spreadsheets()
    # 4 Updates to be done
    # Update userlog with times checked out and new hold on account
    # Update bike summary with checked-out
    # Update bike specific log (add a row)
    # Update helmet log
    hold = user_info[4]
    if hold_long_term:
        hold = holdUpdate(hold, holdToAdd="L")
    hold = holdUpdate(hold, holdToRemove="U")
    now = now_local()

    requests = [

        # Update user log: update hold

        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["UserLog"],
                    "startRowIndex": email_idx + 1,
                    "endRowIndex": email_idx + 2,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5  # ONLY the hold column
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": hold}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "startRowIndex": bike_idx + 1,
                    "endRowIndex": bike_idx + 2,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2  # status column only
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": "Checked-in"}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "startRowIndex": bike_idx + 1,
                    "endRowIndex": bike_idx + 2,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5  # last-user column only
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": ""}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },

        # Insert new row in individual bike log
        {
            "insertDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["Bike" + str(bikeid)],
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 2
                },
                "inheritFromBefore": False
            }
        },

        # Update individual bike log
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Bike" + str(bikeid)],
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 4
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}},
                        {"userEnteredValue": {"stringValue": user_info[0]}},
                        {"userEnteredValue": {"stringValue": "Checked-in"}},
                        {"userEnteredValue": {"stringValue": notes}}
                    ]
                }],
                "fields": "userEnteredValue"
            }
        },
    ]

    if helmetid != -1:
        requests.extend([
            # Insert new row in helmet log
            {
                "insertDimension": {
                    "range": {
                        "sheetId": bike_sheet_dict["HelmetLog"],
                        "dimension": "ROWS",
                        "startIndex": 1,
                        "endIndex": 2
                    },
                    "inheritFromBefore": False
                }
            },

            # Update helmet log
            {
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["HelmetLog"],
                        "startRowIndex": 1,
                        "endRowIndex": 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4
                    },
                    "rows": [{
                        "values": [
                            {"userEnteredValue": {"numberValue": helmetid}},
                            {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}},
                            {"userEnteredValue": {"stringValue": user_info[0]}},
                            {"userEnteredValue": {"stringValue": "Checked-in"}}
                        ]
                    }],
                    "fields": "userEnteredValue"
                }
            }])

    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={'requests': [requests]}
    ).execute()

def holdUpdate(currentHold, holdToAdd = "", holdToRemove = "", tempBanTime = osSettings["tempTimeout"]):
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

def checkin_async(bike, bciw, issues, helmet, photo_path, email, user_list, email_idx, bike_idx):
    try:
        now = now_local()
        if photo_path != "":
            contents = "Bike #"+str(bike)+" is checked in as of "+now.strftime("%m/%d/%Y %H:%M:%S") +".\n Last user was "+email+"\n Photo included:"
            send_gmail(get_gmail_service(),osSettings["adminEmails"],"Bikeshare Return Photo Bike #"+str(bike), contents, photo_path)
        #Here is where we can add an option for this to send issues
        if bciw:
            send_gmail(get_gmail_service(),email,"Forgotten Bike Return #"+str(bike),
                       "Your previously checked-out bike has been checked in by another user. Next time please don't forget to check-in your bike upon return")
            send_gmail(get_gmail_service(),osSettings["adminEmails"],"Forgotten Bike Return #"+str(bike),"User "+email+" did not return their bike and it was marked as returned by another user")
        else:
            send_gmail(get_gmail_service(),email,"Bike #"+str(bike)+" Return Confirmation","Your bike has been successfully checked-in! Thank you for using the bikeshare!")
        driveCheckin(user_list[email_idx],email_idx,bike,bike_idx,helmet,issues)


        blank_issue_responses = {"", "none", "na", "n/a", "no", "nope", "nil", "ok", "okay", "fine", "good", "all good",
                                 "no issue", "no issues", "no problem", "no problems", "nothing", "nothing to report",
                                 "no issues noted", "everything is fine", }

        if issues.strip().lower() not in blank_issue_responses:
            #This means there is an issue to be reported and sent to email
            contents = "Reported issue is: \n" +str(issues)+"Bike #"+str(bike)+" was checked in at "+now.strftime("%m/%d/%Y %H:%M:%S") +".\n Last user was "+email+"\n"
            if photo_path != "":
                send_gmail(get_gmail_service(),osSettings["adminEmails"],"Reported Issue with Bike #"+str(bike),contents+ "Photo included",photo_path)
            else:
                send_gmail(get_gmail_service(),osSettings["adminEmails"],"Reported Issue with Bike #"+str(bike),contents+ "Photo was not included")
    except Exception as e:
        print("Error in checkout_async:", e)

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


@app.route("/")
def index():
    return render_template("cow.html")

if __name__ == "__main__":
    app.run(host = "0.0.0.0", port=5000,debug=True)