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
from urllib.parse import quote





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
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]


app = Flask(__name__)
CORS(app)  # allows your HTML file to communicate with the server
#TEMP VARIABLES TO BE LOADED AS OS SETTINGS


LOCAL_TZ = ZoneInfo("America/Chicago")

def now_local():
    return datetime.now(LOCAL_TZ)



siteResponse = {}
osSettings = {}
bike_sheet_dict = {}
def load_settings():
    bike_sheet_dict.clear()
    spreadsheet = get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
        print(props["title"], props["sheetId"])
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


load_settings()
print(osSettings)


admin_code = [3, now_local()+timedelta(2)]

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
            message_body = (siteResponse["Emails"]["Unlocking"][1] +" #"+str(values[bike_idx][0])+": "
                    +str(values[bike_idx][2])+
                    siteResponse["Emails"]["Unlocking"][2]
            )
            send_gmail(get_gmail_service(),email,siteResponse["Emails"]["Unlocking"][0] + str(values[bike_idx][2]),message_body)
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
    email = values[bike_idx][-1] #This works fine because the range is limited.

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
        #The user who checked out the bike is not on the user list
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
                "textbox": siteResponse["VerifyUser"]["Success"][1] +"<a href=\"/\">Billiken Bikeshare Homepage </a>"
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


#Admin controls
@app.route("/adminLogin",methods=["POST"])
def adminLogin(local_use = False, passCode= None):
    global admin_code
    if local_use == False:
        data = request.get_json()
        passCode = int(data.get("loginCode", ""))
    if osSettings["adminLoginSafety"]:
        email = osSettings["adminEmails"][0]
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
            return False
        if len(values(email_idx)) >= 7:
            admin_code = [values[5],timeExtractor([6])]
        else:
            admin_code = [values[5],now_local()-timedelta(minutes=1)]
    if admin_code[0] == None or admin_code[1] == None:
        if local_use:
            return False, "This code has expired. Get a new one"
        return error("This code has expired. Get a new one",401)
    if admin_code[1] < now_local():
        if local_use:
            return False, "This code has expired. Get a new one"
        return error("This code has expired. Get a new one",401)
    if admin_code[0] != passCode:
        if local_use:
            return False, "The code entered is incorrect or is no longer the code"
        return error("This is no longer the code", 401)
    if local_use:
        return True, None
    return jsonify({
        "topText": "Code entered successfully",
        "textbox": "Welcome to the admin system"
    })





@app.route("/generateAdminCode",methods=["GET"])
def generateAdminCode():
    global admin_code
    admin_code = [randint(10000000, 99999999), now_local() + timedelta(minutes=15)]
    email = osSettings["adminEmails"][0]

    if osSettings["adminLoginSafety"]:
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
            return False
        target = "UserLog!F" + str(email_idx + 1)+":G"+str(email_idx+1)
        body = {'values': [[admin_code[0],admin_code[1].strftime("%m/%d/%Y %H:%M:%S")]]}
        sheet = get_sheets_service().spreadsheets()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID, range=target,
            valueInputOption="USER_ENTERED", body=body).execute()
    full_url = osSettings["PageUrl"]+"/admin?AdminPass="+str(admin_code[0])
    send_gmail(get_gmail_service(),email, "Admin temp code: "+str(admin_code[0]),"<p> For 15 minutes of access the new admin code is: "+str(admin_code[0])
               + "</p> For even easier access use this link: <br> <a href="+full_url+">"+full_url+"</a>")

    return jsonify({
        "topText": "New Code Made",
        "textbox": "The code has been sent to the sluonthemove email with an access link"
    })

@app.route("/allBikeLockCodes", methods = ["POST"])
def allLockCodes():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    RANGE_NAME = "Simple Bike Summary!A2:C"

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
        bikelist.append({"id": row[0], "status": row[1], "color": output_color, "code":row[2]})
    print(bikelist)
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
    })

@app.route("/generateLockCodes", methods = ["POST"])
def generateLockCodes():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    bike_ids = data.get("bike_ids", "")
    skips = []
    if len(bike_ids) > 0:
        skips = sorted(int(x.strip()) for x in bike_ids.split(","))
    RANGE_NAME = "Simple Bike Summary!A2:C"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    new_codes = []
    old_codes = []
    for row in values:
        old_codes.append(int(row[2]))
        if int(row[0]) in skips:
            new_codes.append(int(row[2]))
        else:
            new_codes.append(randint(1000,9999))
    target = "Simple Bike Summary!C2:C"
    body = {
        'values': [[code] for code in new_codes]
    }
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()


    now = now_local()
    current_time = now.strftime("%I:%M %p")
    bikelist = []
    for idx, row in enumerate(values):

        if old_codes[idx] != new_codes[idx]:
            new_color_output = "#88E788"
            old_color_output = "#FFAC1C"

        else:
            new_color_output = "#6FCBF7"
            old_color_output = "#6FCBF7"
        bikelist.append({"id": row[0], "oldCode": old_codes[idx],  "newCode": new_codes[idx], "oldColor": old_color_output,"newColor":new_color_output})
    print(bikelist)
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
    })

@app.route("/addUserWithoutVerification", methods = ["POST"])
def addUserWithoutVerification():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)

    email = data.get("user_email", "")
    email = email.strip().lower()
    print(email)
    if not emailChecker(email, False):
        return error("The email sent was invalid")

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

    addUser(email, False)
    target = "UserLog!G2"
    body = {
        'values': [[""]]
    }
    print(body)
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()

    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been added to the system"
    })

@app.route("/addPaidUser", methods = ["POST"])
def addPaidUser():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email", "")
    email = email.strip().lower()
    dropdown = data.get("dropdownVal", "")
    date_selected = data.get("selectedDate", "")
    if date_selected != "":
        date_selected = datetime.strptime(date_selected, "%Y-%m-%d").date()
    today = date.today()
    if dropdown[:4] == "Fall":
        date_selected = date(today.year, 12, 31)
    elif dropdown[:6] == "Spring":
        date_selected = date(today.year + (today.month > 5), 5, 31)


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
        return error("email is not in the userlist currently")
    new_hold = holdUpdate(values[email_idx][4], holdToRemove="P")
    target = "UserLog!D"+str(email_idx+2)+":E"+str(email_idx+2)
    body = {
        'values': [[date_selected.strftime("%m/%d/%Y"),new_hold]]
    }
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()
    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been added as a dues paying user"
    })

@app.route("/removePaidUser", methods = ["POST"])
def removePaidUser():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email", "")
    email = email.strip().lower()
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
        return error("email is not in the userlist currently")
    if int(values[email_idx][1]) >= 1:
        new_hold = holdUpdate(values[email_idx][4], holdToAdd="P")
    else:
        new_hold = values[email_idx][4]
    target = "UserLog!D"+str(email_idx+2)+":E"+str(email_idx+2)
    body = {
        'values': [["",new_hold]]
    }
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()
    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been removed from the list of users who have paid dues"
    })

@app.route("/giveTimeExtension", methods = ["POST"])
def giveTimeExtension():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email", "")
    email = email.strip().lower()
    RANGE_NAME = "Simple Bike Summary!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    print(values)
    email_idxs = [
        i
        for i, row in enumerate(values)
        if len(row) > 4 and row[4] == email
    ]
    if not email_idxs:
        return error("This user is not currently checking out a bike")
    try:
        ext_time = round(float(data.get("extension_length", "")))
    except:
        return error("You did not enter a whole number of hours")

    for indexes in email_idxs:
        row = values[indexes]
        if len(row) <= 6:
            row.extend([""] * (7 - len(row)))
        new_extension = extensionUpdate(row[6], extensionToAdd='X'*ext_time)
        target = "Simple Bike Summary!G" + str(indexes + 2)
        body = {
            'values': [[new_extension]]
        }
        sheet = get_sheets_service().spreadsheets()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID, range=target,
            valueInputOption="USER_ENTERED", body=body).execute()



    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been given a "+str(ext_time) +" hour extension"
    })

@app.route("/adminCheckoutBike", methods = ["POST"])
def adminCheckoutBike():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    bike_ids = data.get("bike_ids", "")
    skips = []
    if len(bike_ids) > 0:
        check_out_bikes = sorted(int(x.strip()) for x in bike_ids.split(","))
    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    print(values)
    email = osSettings["adminEmails"][0]
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error(email+" which is listed as 1st admin is not in the userlist. This is an error blocking a mass check-out. Orignally this was supposed to be sluonthemove@slu.edu")
    user_info = values[email_idx]
    RANGE_NAME = "Simple Bike Summary!A2:C"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bikes_checked_out = []
    for idx, row in enumerate(values):
        if int(row[0]) in check_out_bikes:
            if row[1] != "Checked-out":
                values[idx][1] = "Checked-out"
                bikes_checked_out.append(int(row[0]))
                driveCheckout(user_info, email_idx, int(row[0]), idx, -1)
                message_body = (siteResponse["Emails"]["Unlocking"][1] + " #" + str(values[idx][0]) + ": "
                                + str(values[idx][2]) +
                                siteResponse["Emails"]["Unlocking"][2]
                                )
                send_gmail(get_gmail_service(), email,
                           siteResponse["Emails"]["Unlocking"][0] + str(values[idx][2]),
                           message_body)
    bikelist = []
    for row in values:
        if row[1] == "Checked-in":
            output_color = "#88E788"
        elif row[1] == "Checked-out":
            output_color = "#FF7F7F"
        else:
            output_color = "#FFAC1C"
        if int(row[0]) in bikes_checked_out:
            checkout_color = "#6FCBF7"
        else:
            checkout_color = "#FFFFFF"
        bikelist.append({"id": row[0], "status": row[1], "color": output_color, "code": row[2], "code_color":checkout_color})
    print(bikelist)
    return jsonify({
        "topText": "Bikes Successfuly checked out",
        "textbox": "These bikes: "+str(bikes_checked_out)+" have been checked out",
        "bike_list":bikelist
    })

@app.route("/forceCheckinBike", methods = ["POST"])
def forceCheckinBike():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    bike_ids = data.get("bike_ids", "")
    skips = []
    if len(bike_ids) > 0:
        check_in_bikes = sorted(int(x.strip()) for x in bike_ids.split(","))

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
    bike_values = result.get("values", "")
    RANGE_NAME = "UserLog!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    user_values = result.get("values", "")
    user_list = [row[0] for row in user_values]

    bikes_checked_in = []
    for idx, row in enumerate(bike_values):
        if int(row[0]) in check_in_bikes:
            bikes_checked_in.append(int(row[0]))
            bike_values[idx][1] = "Checked-in"
            print(row)
            if len(row) > 4:
                now = now_local()
                email = row[-1]
                send_gmail(get_gmail_service(), osSettings["adminEmails"], "Bike #" + str(row[0]) + " Force Check-in",
                           "The prior user was " + email + " and an Admin has now checked-in the bike")
                if email != osSettings["adminEmails"][0]:
                    send_gmail(get_gmail_service(), email, "Bike #" + str(row[0]) + siteResponse["Emails"]["Return"][0],
                               siteResponse["Emails"]["Return"][1])
                if email in user_list:
                    email_idx = user_list.index(email)
                    driveCheckin(user_values[email_idx], email_idx, int(row[0]), idx, -1, "")
                else:
                    driveCheckin(["N/A"], -1, int(row[0]), idx, -1, "")

            else:
                send_gmail(get_gmail_service(), osSettings["adminEmails"], "Bike #" + str(row[0]) + " Force Check-in",
                           "The prior user was not able to be found in sheets and an Admin has now checked-in the bike")
                print(row[0])
                driveCheckin(["N/A"], -1, int(row[0]), idx, -1, "")

    bikelist = []
    for row in bike_values:
        if row[1] == "Checked-in":
            output_color = "#88E788"
        elif row[1] == "Checked-out":
            output_color = "#FF7F7F"
        else:
            output_color = "#FFAC1C"
        bikelist.append(
            {"id": row[0], "status": row[1], "color": output_color, "code": row[2]})
    print(bikelist)
    return jsonify({
        "topText": "Bikes Successfully checked in",
        "textbox": "These bikes: " + str(bikes_checked_in) + " have been checked in",
        "bike_list": bikelist
    })

@app.route("/setNewBikeStatus", methods = ["POST"])
def setNewBikeStatus():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    new_status = data.get("new_status", "")
    new_notes = data.get("new_notes", "")
    dropdownVal = data.get("dropdownVal", "")
    if new_status.strip() == "" or int(dropdownVal) == -1:
        return error("Did not enter a full status or select a bike")
    RANGE_NAME = "Simple Bike Summary!A2:D"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    for idx, row in enumerate(values):
        if int(row[0]) == int(dropdownVal):
            target = "Simple Bike Summary!B" + str(idx + 2)+":"+str(idx + 2)
            body = {
                'values': [[new_status,row[2],new_notes,"","",""]]
            }
            sheet = get_sheets_service().spreadsheets()
            sheet.values().update(
                spreadsheetId=SPREADSHEET_ID, range=target,
                valueInputOption="USER_ENTERED", body=body).execute()
            break

    return jsonify({
        "topText": "New Bike Status set",
        "textbox": "This bike: " + str(dropdownVal) + " has been set to a new status of: "+ str(new_status)
    })

@app.route("/removeBikeFromSystem", methods = ["POST"])
def removeBikeFromSystem():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    bikeid = data.get("bikeid", "")
    RANGE_NAME = "Simple Bike Summary!A2:G"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike_list = [int(row[0]) for row in values]
    if int(bikeid) in bike_list:
        bike_idx = bike_list.index(int(bikeid))
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "dimension": "ROWS",
                    "startIndex": bike_idx + 1,
                    "endIndex": bike_idx + 2
                },
            }
        }]
        sheet.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': [requests]}
        ).execute()
        return jsonify({
        "topText": "Bike Successfully Removed",
        "textbox": "<p>This bike: " + str(bikeid) + " has been removed from the system and can no longer be checked out. </p> The log sheet for the bike has not been removed but can be removed manually"
    })
    else:
        return jsonify({
        "topText": "Bike Failed to be Removed",
        "textbox": "This bike: " + str(bikeid) + " was not able to be found on the list"
    })

@app.route("/addBikeToSystem", methods = ["POST"])
def addBikeToSystem():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    bikeid = data.get("bikeid", "")
    try:
        bikeid = int(bikeid)
        if bikeid <= 0:
            return error("The bikeid entered was not a whole number")

    except:
        return error("The bikeid entered was not a whole number")
    RANGE_NAME = "Simple Bike Summary!A2:D"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike_ids = [int(row[0]) for row in values]
    if bikeid in bike_ids:
        return error("This bikeid is already being used in the system")

    bike_ids.append(bikeid)
    bike_ids.sort()
    bike_idx = bike_ids.index(bikeid)
    random_lock_code = randint(1000,9999)
    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "dimension": "ROWS",
                    "startIndex": bike_idx+1,
                    "endIndex": bike_idx+2
                },
                "inheritFromBefore": False
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": bike_sheet_dict["Simple Bike Summary"],
                    "startRowIndex": bike_idx+1,
                    "endRowIndex": bike_idx+2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3
                },
                "rows": [
                    {
                        "values": [
                            {"userEnteredValue": {"numberValue": bikeid}},
                            {"userEnteredValue": {"stringValue": "Checked-in"}},
                            {"userEnteredValue": {"numberValue": random_lock_code}},
                                                    ]
                    }
                ],
                "fields": "userEnteredValue"
            }
        }
    ]

    if "Bike"+str(bikeid) not in bike_sheet_dict:
        code_set = False
        while not code_set:
            new_sheet_id = randint(100000000,999999999)
            if new_sheet_id not in set(bike_sheet_dict.values()):
                bike_sheet_dict["Bike"+str(bikeid)] = new_sheet_id
                code_set = True
        requests.extend([{
            "addSheet": {
                "properties": {
                    "sheetId": bike_sheet_dict["Bike"+str(bikeid)],
                    "title": "Bike"+str(bikeid),
                    "gridProperties": {
                        "rowCount": 5,
                        "columnCount": 10
                    }
                }
            }
        }
        ])
        requests.extend([
            {
                "updateCells": {
                    "range": {
                        "sheetId": bike_sheet_dict["Bike"+str(bikeid)],
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4
                    },
                    "rows": [
                        {
                            "values": [
                                {"userEnteredValue": {"stringValue": "Timestamp"}},
                                {"userEnteredValue": {"stringValue": "User ID"}},
                                {"userEnteredValue": {"stringValue": "Checking in/Out/Maintenance"}},
                                {"userEnteredValue": {"stringValue": "Notes"}},
                            ]
                        }
                    ],
                    "fields": "userEnteredValue"
                }
            }
        ])

    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={'requests': [requests]}
    ).execute()


    return jsonify({
        "topText": "Bike #"+str(bikeid)+" has been added",
        "textbox": "This bike has been added to the system and the randomly assigned lock code is <b> "+str(random_lock_code)+"</b>"
    })

@app.route("/getHelmetList", methods = ["POST"])
def getHelmetList():
    return jsonify({
        "textbox": "The current helmets listed in the system are: <br>"+str(osSettings["helmets"])
    })

@app.route("/addHelmets", methods = ["POST"])
def addHelmets():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    helmets = data.get("helmetList", "")
    print(helmets)
    skips = []
    if len(helmets) > 0:
        new_helmets = sorted(int(x.strip()) for x in helmets.split(","))
    else:
        return error("no helmets were entered in the box to be added")
    new_helmets.extend( osSettings["helmets"])
    new_helmets.sort()
    new_helmets = list(dict.fromkeys(new_helmets))
    osSettings["helmets"] = new_helmets

    target = "osSettings!B1"
    body = {
        'values': [new_helmets]
    }
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()

    return jsonify({
        "topText": "Helmets have been added",
        "textbox": "The new helmet list is <br>"+str(new_helmets)
    })

@app.route("/removeHelmets", methods = ["POST"])
def removeHelmets():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    helmets = data.get("helmetList", "")
    print(helmets)
    skip_helmets = []
    if len(helmets) > 0:
        skip_helmets = sorted(int(x.strip()) for x in helmets.split(","))
    else:
        return error("no helmets were entered in the box to be removed")
    new_helmets = []
    removed_count = 0
    for helm in osSettings["helmets"]:
        if helm not in skip_helmets:
            new_helmets.append(helm)
        else:
            removed_count+=1

    new_helmets.sort()
    new_helmets = list(dict.fromkeys(new_helmets))
    osSettings["helmets"] = new_helmets
    sheets_new_helmets = new_helmets + ([""] *removed_count)
    target = "osSettings!B1"
    body = {
        'values': [sheets_new_helmets]
    }
    sheet = get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()

    return jsonify({
        "topText": "Helmets have been removed",
        "textbox": "The new helmet list is <br>"+str(new_helmets)
    })

@app.route("/lastBikeUsers", methods = ["POST"])
def lastBikeUsers():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    RANGE_NAME = "Simple Bike Summary!A2:B"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    bike_list = [str(row[0]) for row in values]
    ranges = []
    for bikeid in bike_list:
        ranges.append("Bike"+bikeid+"!B2")

    sheet = get_sheets_service().spreadsheets()
    # The single batch call
    requests = sheet.values().batchGet(
        spreadsheetId=SPREADSHEET_ID,
        ranges=ranges
    )
    response = requests.execute()

    value_ranges = response.get('valueRanges', [])

    now = now_local()
    current_time = now.strftime("%I:%M %p")
    bikelist = []
    for idx, row in enumerate(values):
        if row[1] == "Checked-in":
            output_color = "#88E788"
            user_color = "#33B5E5"
        elif row[1] == "Checked-out":
            output_color = "#FF7F7F"
            user_color = "#FFD300"
        else:
            output_color = "#FFAC1C"
            user_color = "#33B5E5"
        last_user = value_ranges[idx].get('values', [])

        bikelist.append({"id": row[0], "status": row[1], "color": output_color, "user": last_user, "user_color": user_color})
    print(bikelist)
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
    })

@app.route("/reloadSiteSettings", methods = ["POST"])
def reloadSiteSettings():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    load_settings()
    return jsonify({
        "topText": "Success at reloading site settings",
        "textbox": "The site has updated with the new OS settings"
    })

def error(message, status=400):
    return jsonify({"error": message}), status


def addUser(email, send_email = True):
    now = now_local()
    sheet = get_sheets_service().spreadsheets()
    today = date.today()
    account_expiration = date(today.year + (today.month > 5), 5, 31)
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
                            {"userEnteredValue": {"stringValue": account_expiration.strftime("%m/%d/%Y") }},
                            {},{},  # intentionally empty
                            {"userEnteredValue": {"numberValue": verification_code}},
                            {"userEnteredValue": {"stringValue": code_expiration.strftime("%m/%d/%Y %H:%M:%S")}}
                        ]
                    }
                ],
                "fields": "userEnteredValue"
            }
        }
    ]
    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={'requests': [requests]}
    ).execute()
    safe_email = quote(email)
    message_body = ( siteResponse["Emails"]["Verification"][1]+
            "<a href=" + osSettings["PageUrl"]+"/?email=" + safe_email + "&code=" + str(verification_code) + ">Verify by clicking here </a>"
                     + siteResponse["Emails"]["Verification"][2]+ "<a href="+osSettings["PageUrl"]+"/?vp=1>"+osSettings["PageUrl"]+"/?vp=1 </a>"
    )
    if send_email:
        send_gmail(get_gmail_service(),email, siteResponse["Emails"]["Verification"][0] + str(verification_code),message_body)

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
                    "endColumnIndex": 6  # last-user column and timestamp
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": user_info[0]}},
                        {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}}
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


    now = now_local()

    requests = [
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
                    "endColumnIndex": 7  # last-user column and timestamp
                },
                "rows": [{
                    "values": [
                        {"userEnteredValue": {"stringValue": ""}},
                        {"userEnteredValue": {"stringValue": ""}},
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

    if user_info[0] != "N/A":
        hold = user_info[4]
        if hold_long_term:
            hold = holdUpdate(hold, holdToAdd="L")
        hold = holdUpdate(hold, holdToRemove="U")
        requests.extend([
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
        }
        ])

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
    print(requests)

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


def checkin_async(bike, bciw, issues, helmet, photo_path, email, user_list, email_idx, bike_idx):
    try:
        now = now_local()
        if photo_path != "":
            contents = "<p> Bike #"+str(bike)+" is checked in as of: <br>"+now.strftime("%m/%d/%Y %H:%M:%S") +".</p><p> Last user was: <br>"+email+"</p> Photo included:"
            send_gmail(get_gmail_service(),osSettings["adminEmails"][0],"Bikeshare Return Photo Bike #"+str(bike), contents, photo_path)
        #Here is where we can add an option for this to send issues
        if bciw:
            send_gmail(get_gmail_service(),email,siteResponse["Emails"]["ForgottenReturn"][0]+str(bike),
                       siteResponse["Emails"]["ForgottenReturn"][1])
            send_gmail(get_gmail_service(),osSettings["adminEmails"],"Forgotten Bike Return #"+str(bike),"User "+email+" did not return their bike and it was marked as returned by another user")
        else:
            send_gmail(get_gmail_service(),email,"Bike #"+str(bike)+siteResponse["Emails"]["Return"][0],siteResponse["Emails"]["Return"][1])
        driveCheckin(user_list[email_idx],email_idx,bike,bike_idx,helmet,issues)

        blank_issue_responses = {
                                    s.strip().lower()
                                    for s in osSettings["blankResponses"]
                                    if s is not None
                                } | {""}

        if issues.strip().lower() not in blank_issue_responses:
            #This means there is an issue to be reported and sent to email
            contents = "<p> Reported issue is: <br>" +str(issues)+"<p> Bike #"+str(bike)+" was checked in at: <br>"+now.strftime("%m/%d/%Y %H:%M:%S") +".</p> <p>Last user was: <br>"+email+"</p>"
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

@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host = "0.0.0.0", port=5000,debug=True)