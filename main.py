from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import json, base64
import threading
from datetime import datetime, date, timedelta
from random import randint
from dotenv import load_dotenv
from email_validator import validate_email, EmailNotValidError
from urllib.parse import quote
import services
import logging
import sys
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image

logging.basicConfig(
    level=logging.INFO,  # change to DEBUG if needed
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

#logger.info("Server started")
#logger.debug("User ID: %s", user_id)
#logger.warning("Something suspicious happened")
#logger.error("Something failed")
#logger.exception("Crash happened")


load_dotenv("passwords.env")


SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=3, x_proto=1)

CORS(app)  # allows your HTML file to communicate with the server
#TEMP VARIABLES TO BE LOADED AS OS SETTINGS


services.load_settings()
logger.info("Server started")


admin_code = [3, services.now_local()+timedelta(days=2)]
#admin_code = [None, None]

def log_memory():
    import psutil
    process = psutil.Process(os.getpid())

    process_ram = process.memory_info().rss / (1024 ** 2)
    system = psutil.virtual_memory()

    logger.info(
        f"Process RAM: {process_ram:.1f} MB | "
        f"System RAM: {system.used / (1024 ** 2):.1f}/{system.total / (1024 ** 2):.1f} MB"
    )


def compress_photo(input_path, output_path, max_size=(1920, 1920), quality=70):
    """
    Resize and compress photo.
    - max_size: max width/height
    - quality: JPEG quality
    """
    img = Image.open(input_path)
    img.thumbnail(max_size)  # maintains aspect ratio
    img.save(output_path, format="JPEG", quality=quality)
    img.close()
    return output_path

@app.route("/table", methods=["GET"])
def bike_table():
    RANGE_NAME = "Simple Bike Summary!A2:B"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    now = services.now_local()
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

    logger.debug("Returned Basic Bike Table")
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
        "topText": services.siteResponse["InitialPage"]["Table"][0],
        "textbox": services.siteResponse["InitialPage"]["Table"][1]
    })

@app.route("/status", methods=["POST"])
def bike_status():
    data = request.get_json()
    bikeid = int(data.get("bikeid", ""))
    # Do something with the text:
    RANGE_NAME = "Simple Bike Summary!A2:B"
    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    try:
        bike_ids = [int(row[0]) for row in values]
    except:
        pass
        #EMAIL ERROR CODE TO SLU EMAIL CONSIDER ADDING ADMINLIST
        #send_email("Error in bike_status function due to not all list items being integers. Check the bikeid list on the Bike Summary page to see if there are any non number bikeids", "erictmans@gmail.com","ERROR on BIKESHARE server")
    if bikeid in bike_ids:
        idx = bike_ids.index(bikeid)
    else:
        logger.warning("User went for bike #"+str(bikeid)+" and it didn't exist")
        return (jsonify({
            "status": 2,
            "statusText": services.siteResponse["InitialPage"]["NotFound"][0],
            "text1": services.siteResponse["InitialPage"]["NotFound"][1]
        }))


    if values[idx][1] == "Checked-in":
        logger.debug("Bike #"+str(bikeid)+" was returned as Checked-in")
        return jsonify({
            "status": 0,
            "text1": services.siteResponse["InitialPage"]["Checked-in"][1],
            "helmetList": services.osSettings["HelmetList"]
        })
    elif values[idx][1] == "Checked-out":
        logger.debug("Bike #"+str(bikeid)+" was returned as Checked-out")

        return jsonify({
            "status":1,
            "text1": services.siteResponse["InitialPage"]["Checked-out"][1],
            "text2": services.siteResponse["InitialPage"]["Checked-out"][2],
            "helmetList": services.osSettings["HelmetList"]
        })
    else:
        logger.debug("Bike #"+str(bikeid)+" was returned as a different status")

        RANGE_NAME = "Simple Bike Summary!D"+str(idx+2) #Plus 2 for the title row not read, and that excel starts at 1 not 0
        sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        #This email is not in user list. Now we need to do rigorous checking
        emailLegit = emailChecker(email)
        if emailLegit:
            logger.info("User "+email+" was added to the email list for the first time")
            addUser(email)
            return jsonify({
        "topText": services.siteResponse["Check-out"]["FirstTime"][0],
        "textbox": services.siteResponse["Check-out"]["FirstTime"][1]
    })

        else:
            logger.debug("Email "+email+ " did not meet the requirements to be added")
            return jsonify({
                "topText": services.siteResponse["Check-out"]["BadEmail"][0],
                "textbox": services.siteResponse["Check-out"]["BadEmail"][1]
            })
    #Now we are dealing with people in the user list! that is fun.
    #Main checks Are they verified, do they have a free ride - > have they paid ->
    user_info = values[email_idx]
    verification_time = user_info[6] if len(user_info) > 6 else None
    if verification_time:
        logger.info("User " + email + " was rejected for not being verified")

        return jsonify({
            "topText": services.siteResponse["Check-out"]["NotYetVerified"][0],
            "textbox": services.siteResponse["Check-out"]["NotYetVerified"][1]
        })
    hold_status = user_info[4]
    if user_info[3] == "" and int(user_info[1]) >= 2:
        hold_status = services.holdUpdate(hold_status, holdToAdd = "P", tempBanTime = services.osSettings["tempTimeout"])
        #This is a scuffed dues based hold. A permanent one should be added
    hold, output = holdChecker(hold_status) #EDIT MAX AMOUNT OF BIKES CHECKED OUT
    if hold:
        logger.info("User " + email + " was rejected for having a hold with notes: "+output[1])
        return jsonify({
            "topText": output[0],
            "textbox": output[1]
        })

    #Congrats, they are good to check out a bike. Now we doublecheck the bike is good to check out and then send code
    RANGE_NAME = "Simple Bike Summary!A2:E"

    sheet = services.get_sheets_service().spreadsheets()
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
            message_body = (services.siteResponse["Emails"]["Unlocking"][1] +" #"+str(values[bike_idx][0])+": "
                    +str(values[bike_idx][2])+
                    services.siteResponse["Emails"]["Unlocking"][2]
            )
            services.send_gmail(services.get_gmail_service(),email,services.siteResponse["Emails"]["Unlocking"][0] + str(values[bike_idx][2]),message_body)
            logger.info("User "+email+" Checked out bike #"+str(bike))
            return jsonify({
                "topText": services.siteResponse["Check-out"]["Success"][0],
                "textbox": services.siteResponse["Check-out"]["Success"][1]
            })
        logger.info("User " + email + " Failed to check out bike #" + str(bike) +" most likely someone else checked the bike out while they were using it form")

        return jsonify({
                "topText": services.siteResponse["Check-out"]["Fail"][0],
                "textbox": services.siteResponse["Check-out"]["Fail"][1]
        })
    logger.error("User " + email + " was able to run check-out script for bike #"+ str(bike)+" but the server was unable to find the bike. This shouldn't happen")

    return jsonify({
        "topText": services.siteResponse["Check-out"]["Error14"][0],
        "textbox": services.siteResponse["Check-out"]["Error14"][1]
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
    #does this cause errors?
    RANGE_NAME = "Simple Bike Summary!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike_list = [int(row[0]) for row in values]
    if bike in bike_list:
        bike_idx = bike_list.index(bike)
    else:
        logger.error("Bike #"+str(bike)+" was attempted to be returned the server was unable to find the bike. This shouldn't happen")

        return jsonify({
            "topText": services.siteResponse["Check-in"]["Error11"][0],
            "textbox": services.siteResponse["Check-in"]["Error11"][1]
        })
    #This checks if there is an automatic hold on the account after x number of hours overdue
    L_hold = False
    if services.osSettings["overdueHoldLength"] != -1:
        checked_out_time = services.timeExtractor(values[bike_idx][5])
        norm_hours = services.osSettings["checkOutLength"]
        if len(values[bike_idx]) >= 7:
            extension, hour_count = services.extensionChecker(values[bike_idx][6])
            if extension:
                if hour_count is not None:
                    norm_hours += hour_count
        now = services.now_local()
        holdLevelDue = checked_out_time + timedelta(hours=(norm_hours+services.osSettings["overdueHoldLength"]))
        if now > holdLevelDue:
            L_hold = True

    email = values[bike_idx][4]
    email = email.strip().lower()
    # Find if email is in list
    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        logger.error("User: "+email+"was listed as having a bike checked out but couldn't be found on the userlist. This shouldn't happen")

        #The user who checked out the bike is not on the user list
        return jsonify({
            "topText": services.siteResponse["Check-in"]["Error12"][0],
            "textbox": services.siteResponse["Check-in"]["Error12"][1]
        })
        #Also a shitty error
    user_list = values
    photo_path = ""
    try:
        if photo:
            tmp_path = f"/tmp/{photo.filename}"
            photo.save(tmp_path)
            compressed_path = f"/tmp/compressed_{photo.filename}"
            compress_photo(tmp_path, compressed_path)
            photo_path = compressed_path
            os.remove(tmp_path)  # remove original large upload

    except Exception as e:
        logger.error("User: "+email+" bike id #" + str(bike)+" was able to submit without a photo")

        print("Error in checkout_async:", e)

    threading.Thread(
        target=checkin_async,
        args=(
            bike, bciw, issues, helmet, photo_path, email,
            user_list[email_idx], email_idx, bike_idx, L_hold
        ),
        daemon=False
    ).start()

    logger.info("User: " + email + " bike id #" + str(bike) + " bike was checked in")
    return jsonify({
        "topText": services.siteResponse["Check-in"]["Success"][0],
        "textbox": services.siteResponse["Check-in"]["Success"][1]
    })


@app.route("/submitVerify",methods=["POST"])
def verifyUser():
    data = request.get_json()
    email = data.get("email", "")
    email = email.strip().lower()
    verificationCode = data.get("verificationCode","")
    newCode = data.get("newCode",[])
    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        logger.info("User with email: "+email+" tried to verify themself but they were not in the system.")
        return jsonify({
        "topText": services.siteResponse["VerifyUser"]["NotInSystem"][0],
        "textbox": services.siteResponse["VerifyUser"]["NotInSystem"][1]
    })
    user_info = values[email_idx]
    now = services.now_local()
    try:
        ver_time = user_info[6]
    except:
        logger.info("User with email: "+email+" tried to verify themself but they were already verified.")

        return jsonify({
        "topText": services.siteResponse["VerifyUser"]["AlreadyDone"][0],
        "textbox": services.siteResponse["VerifyUser"]["AlreadyDone"][1]
    })
    if newCode:
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
        logger.info("User with email: "+email+" has been given a new code to verify themselves.")

        return jsonify({
            "topText": services.siteResponse["VerifyUser"]["NewCode"][0],
            "textbox": services.siteResponse["VerifyUser"]["NewCode"][1]
        })

    temp = services.timeExtractor(ver_time)

    if temp >= now:
        #We are within time.
        if str(user_info[5]) == str(verificationCode.strip()):
        #Success. This account can be verified
            sheet.values().clear(
                spreadsheetId=SPREADSHEET_ID,
                range="UserLog!G"+str(email_idx+2)
            ).execute()

            logger.info("User with email: "+email+" was verified.")

            return jsonify({
                "topText": services.siteResponse["VerifyUser"]["Success"][0],
                "textbox": services.siteResponse["VerifyUser"]["Success"][1] +"<a href=\"/\">Billiken Bikeshare Homepage </a>"
            })
        else:
            logger.info("User with email: "+email+" entered the wrong code.")

            return jsonify({
                "topText": services.siteResponse["VerifyUser"]["Wrong"][0],
                "textbox": services.siteResponse["VerifyUser"]["Wrong"][1]
            })
    else:
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
        logger.info("User with email: " + email + " was too slow to be verified and was given a new code.")

        return jsonify({
            "topText": services.siteResponse["VerifyUser"]["TooSlow"][0],
            "textbox": services.siteResponse["VerifyUser"]["TooSlow"][1]
        })

@app.route("/bikeQRcode", methods=["POST"])
def bikeQRcode():
    data = request.get_json()
    qrCode = data.get("QRcodeBike", "")
    if qrCode in services.qr_codes_to_bike_id:
        return jsonify({
            "bikeid": services.qr_codes_to_bike_id[qrCode]
        })
    return error("There has been an error in the code. This QR code does not match up to any bike in the system")

#Admin controls
@app.route("/adminLogin",methods=["POST"])
def adminLogin(local_use = False, passCode= None):
    global admin_code
    if local_use == False:
        data = request.get_json()
        passCode = int(data.get("loginCode", ""))
    if services.osSettings["adminLoginSafety"]:
        email = services.osSettings["AdminEmails"][0]
        RANGE_NAME = "UserLog!A2:G"

        sheet = services.get_sheets_service().spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME
        ).execute()
        values = result.get("values", "")
        user_list = [row[0] for row in values]
        if email in user_list:
            email_idx = user_list.index(email)
        else:
            return False
        row = values[email_idx]


        if len(row) >= 7:
            admin_code = [
                int(row[5]),
                services.timeExtractor(row[6])
            ]
        else:
            admin_code = [
                int(row[5]),
                services.now_local() - timedelta(minutes=1)
            ]

    if admin_code[0] == None or admin_code[1] == None:
        if local_use:
            return False, "The code has expired. Get a new one <a href=\"/admin\">Click Here To Start Over</a>"
        return error("The code has expired. Get a new one <a href=\"/admin\">Click Here To Start Over</a>",401)
    if admin_code[0] != passCode:
        if local_use:
            return False, "This is no longer the code <a href=\"/admin\">Click Here To Start Over</a>"
        return error("This is no longer the code <a href=\"/admin\">Click Here To Start Over</a>", 401)
    if admin_code[1] < services.now_local():
        if local_use:
            return False, "The code has expired. Get a new one <a href=\"/admin\">Click Here To Start Over</a>"
        return error("The code has expired. Get a new one <a href=\"/admin\">Click Here To Start Over</a>",401)
    if local_use:
        return True, None
    return jsonify({
        "topText": "Code entered successfully",
        "textbox": "Welcome to the admin system"
    })





@app.route("/generateAdminCode",methods=["GET"])
def generateAdminCode():
    global admin_code
    admin_code = [randint(10000000, 99999999), services.now_local() + timedelta(minutes=15)]
    email = services.osSettings["AdminEmails"][0]

    if services.osSettings["adminLoginSafety"]:
        RANGE_NAME = "UserLog!A2:G"

        sheet = services.get_sheets_service().spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME
        ).execute()
        values = result.get("values", "")
        user_list = [row[0] for row in values]
        if email in user_list:
            email_idx = user_list.index(email)
        else:
            return False
        target = "UserLog!F" + str(email_idx + 2)+":G"+str(email_idx+2)
        body = {'values': [[admin_code[0],admin_code[1].strftime("%m/%d/%Y %H:%M:%S")]]}
        sheet = services.get_sheets_service().spreadsheets()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID, range=target,
            valueInputOption="USER_ENTERED", body=body).execute()
    full_url = services.osSettings["PageUrl"]+"/admin?AdminPass="+str(admin_code[0])
    services.send_gmail(services.get_gmail_service(),email, "Admin temp code: "+str(admin_code[0]),"<p> For 15 minutes of access the new admin code is: "+str(admin_code[0])
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    now = services.now_local()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    new_codes = []
    old_codes = []
    changed = []
    for row in values:
        old_codes.append(int(row[2]))
        if int(row[0]) in skips:
            new_codes.append(int(row[2]))
        else:
            code = randint(1000,9999)
            new_codes.append(code)
            changed.append((int(row[0]), code))

    target = "Simple Bike Summary!C2:C"
    body = {
        'values': [[code] for code in new_codes]
    }
    sheet = services.get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()

    requests = [{

        "insertDimension": {
            "range": {
                "sheetId": services.bike_sheet_dict["LockLog"],
                "dimension": "ROWS",
                "startIndex": 1,
                "endIndex": 1+len(changed)
            },
            "inheritFromBefore": False
        }

    }]

    now = services.now_local()
    for idx, (ids,code) in enumerate(changed):
        requests.extend([{

            "updateCells": {
                "range": {
                    "sheetId": services.bike_sheet_dict["LockLog"],
                    "startRowIndex": 1+idx,
                    "endRowIndex": 2+idx,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3
                },
                "rows": [
                    {
                        "values": [
                            {"userEnteredValue": {"numberValue": ids}},
                            {"userEnteredValue": {"numberValue": code}},
                            {"userEnteredValue": {"stringValue": now.strftime("%m/%d/%Y %H:%M:%S")}},
                                                    ]
                    }
                ],
                "fields": "userEnteredValue"
            }

        }])

    services.get_sheets_service().spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests}
    ).execute()

    now = services.now_local()
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
    if not emailChecker(email, False):
        return error("The email sent was invalid")

    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
    sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error("The email you entered is not currently in the user list")
    new_hold = services.holdUpdate(values[email_idx][4], holdToRemove="P", tempBanTime = services.osSettings["tempTimeout"])
    target = "UserLog!D"+str(email_idx+2)+":E"+str(email_idx+2)
    body = {
        'values': [[date_selected.strftime("%m/%d/%Y"),new_hold]]
    }
    sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error("The email you entered is not currently in the user list")
    if int(values[email_idx][1]) >= 1:
        new_hold = services.holdUpdate(values[email_idx][4], holdToAdd="P", tempBanTime = services.osSettings["tempTimeout"])
    else:
        new_hold = values[email_idx][4]
    target = "UserLog!D"+str(email_idx+2)+":E"+str(email_idx+2)
    body = {
        'values': [["",new_hold]]
    }
    sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    email_idxs = [
        i
        for i, row in enumerate(values)
        if len(row) > 4 and row[4] == email
    ]
    if not email_idxs:
        return error("This user is not currently checking out a bike. They must be to get a time extension")
    try:
        ext_time = round(float(data.get("extension_length", "")))
    except:
        return error("You must enter a whole number of hours")

    for indexes in email_idxs:
        row = values[indexes]
        if len(row) <= 6:
            row.extend([""] * (7 - len(row)))
        new_extension = services.extensionUpdate(row[6], extensionToAdd='X'*ext_time)
        target = "Simple Bike Summary!G" + str(indexes + 2)
        body = {
            'values': [[new_extension]]
        }
        sheet = services.get_sheets_service().spreadsheets()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID, range=target,
            valueInputOption="USER_ENTERED", body=body).execute()



    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been given a "+str(ext_time) +" hour extension"
    })

@app.route("/giveBonusBikes", methods = ["POST"])
def giveBonusBikes():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email", "")
    email = email.strip().lower()
    RANGE_NAME = "UserLog!A2:E"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")

    user_list = [row[0] for row in values]


    if email not in user_list:
        return error("This user is not on the user list. They must be")
    else:
        email_idx = user_list.index(email)


    try:
        bonus_bikes = round(float(data.get("bonus_bikes", "")))
    except:
        return error("You must enter a whole number of hours")
    associated_num = 0
    if len(values[email_idx]) > 4:
        code = values[email_idx][4]
        if "X" in code:
            position = code.index("X")
            associated_num = int(code[position + 1: position + 3], 16)
    new_hold = ""
    if associated_num > bonus_bikes:
        new_hold = services.holdUpdate(code, holdToRemove='X'*(associated_num-bonus_bikes))
    else:
        new_hold = services.holdUpdate(code, holdToAdd='X'*(bonus_bikes-associated_num))

    target = "UserLog!E" + str(email_idx + 2)
    body = {
        'values': [[new_hold]]
    }
    sheet = services.get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()



    return jsonify({
        "topText": "Success",
        "textbox": "The user: "+email+" has been given the ability to check out "+str(bonus_bikes) +" bonus bikes"
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    email = services.osSettings["AdminEmails"][0]
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error(email+" which is listed as 1st admin is not in the userlist. This is an error blocking a mass check-out. Originally this was supposed to be sluonthemove@slu.edu. Add that user to the userlist manually on the spreadsheet")
    user_info = values[email_idx]
    RANGE_NAME = "Simple Bike Summary!A2:C"

    sheet = services.get_sheets_service().spreadsheets()
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
                message_body = (services.siteResponse["Emails"]["Unlocking"][1] + " #" + str(values[idx][0]) + ": "
                                + str(values[idx][2]) +
                                services.siteResponse["Emails"]["Unlocking"][2]
                                )
                services.send_gmail(services.get_gmail_service(), email,
                           services.siteResponse["Emails"]["Unlocking"][0] + str(values[idx][2]),
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    bike_values = result.get("values", "")
    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
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
            if len(row) > 4:
                now = services.now_local()
                L_hold = False
                email = row[-1]
                services.send_gmail(services.get_gmail_service(), services.osSettings["AdminEmails"], "Bike #" + str(row[0]) + " Force Check-in",
                           "The prior user was " + email + " and an Admin has now checked-in the bike")
                if email != services.osSettings["AdminEmails"][0]:
                    services.send_gmail(services.get_gmail_service(), email, "Bike #" + str(row[0]) + services.siteResponse["Emails"]["Return"][0],
                               services.siteResponse["Emails"]["Return"][1])
                    if services.osSettings["overdueHoldLength"] != -1:
                        checked_out_time = services.timeExtractor(row[5])
                        norm_hours = services.osSettings["checkOutLength"]
                        if len(row) >= 7:
                            extension, hour_count = services.extensionChecker(row[6])
                            if extension:
                                if hour_count is not None:
                                    norm_hours += hour_count
                        holdLevelDue = checked_out_time + timedelta(
                            hours=(norm_hours + services.osSettings["overdueHoldLength"]))
                        if now > holdLevelDue:
                            L_hold = True
                if email in user_list:
                    email_idx = user_list.index(email)
                    driveCheckin(user_values[email_idx], email_idx, int(row[0]), idx, -1, "", L_hold)
                    if L_hold:
                        services.send_gmail(services.get_gmail_service(), email,
                                            services.siteResponse["Emails"]["AutomaticHold"][0],
                                            services.siteResponse["Emails"]["AutomaticHold"][1])
                        services.send_gmail(services.get_gmail_service(), services.osSettings["AdminEmails"],
                                            "Automatic Hold on User Account",
                                            "<p>User " + email + " did not return their bike within the alloted time and now has a hold and is unable to check out bikes. </p> To remove the hold use the admin panel or manually edit the sheet")

                else:
                    driveCheckin(["N/A"], -1, int(row[0]), idx, -1, "")

            else:
                services.send_gmail(services.get_gmail_service(), services.osSettings["AdminEmails"], "Bike #" + str(row[0]) + " Force Check-in",
                           "The prior user was not able to be found in sheets and an Admin has now checked-in the bike")
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
        return error("You did not enter a full status or select a bike")
    RANGE_NAME = "Simple Bike Summary!A2:D"

    sheet = services.get_sheets_service().spreadsheets()
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
            sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
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
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
            return error("The bikeid entered must be a whole number")

    except:
        return error("The bikeid entered must be a whole number")
    RANGE_NAME = "Simple Bike Summary!A2:D"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    bike_ids = [int(row[0]) for row in values]
    if bikeid in bike_ids:
        return error("That bike id number is already being used in the system")

    bike_ids.append(bikeid)
    bike_ids.sort()
    bike_idx = bike_ids.index(bikeid)
    random_lock_code = randint(1000,9999)
    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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

    if "Bike"+str(bikeid) not in services.bike_sheet_dict:
        code_set = False
        while not code_set:
            new_sheet_id = randint(100000000,999999999)
            if new_sheet_id not in set(services.bike_sheet_dict.values()):
                services.bike_sheet_dict["Bike"+str(bikeid)] = new_sheet_id
                code_set = True
        requests.extend([{
            "addSheet": {
                "properties": {
                    "sheetId": services.bike_sheet_dict["Bike"+str(bikeid)],
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
                        "sheetId": services.bike_sheet_dict["Bike"+str(bikeid)],
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
        "textbox": "The current helmets listed in the system are: <br>"+str(services.osSettings["HelmetList"])
    })

@app.route("/addHelmets", methods = ["POST"])
def addHelmets():
    data: object = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    helmets = data.get("helmetList", "")
    skips = []
    if len(helmets) > 0:
        new_helmets = sorted(int(x.strip()) for x in helmets.split(","))
    else:
        return error("No helmets were entered in the textbox")
    new_helmets.extend( services.osSettings["HelmetList"])
    new_helmets.sort()
    new_helmets = list(dict.fromkeys(new_helmets))
    services.osSettings["HelmetList"] = new_helmets

    target = "osSettings!B1"
    body = {
        'values': [new_helmets]
    }
    sheet = services.get_sheets_service().spreadsheets()
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
    skip_helmets = []
    if len(helmets) > 0:
        skip_helmets = sorted(int(x.strip()) for x in helmets.split(","))
    else:
        return error("no helmets were entered in the textbox")
    new_helmets = []
    removed_count = 0
    for helm in services.osSettings["HelmetList"]:
        if helm not in skip_helmets:
            new_helmets.append(helm)
        else:
            removed_count+=1

    new_helmets.sort()
    new_helmets = list(dict.fromkeys(new_helmets))
    services.osSettings["HelmetList"] = new_helmets
    sheets_new_helmets = new_helmets + ([""] *removed_count)
    target = "osSettings!B1"
    body = {
        'values': [sheets_new_helmets]
    }
    sheet = services.get_sheets_service().spreadsheets()
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

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", [])
    bike_list = [str(row[0]) for row in values]
    ranges = []
    for bikeid in bike_list:
        ranges.append("Bike"+bikeid+"!B2")

    sheet = services.get_sheets_service().spreadsheets()
    # The single batch call
    requests = sheet.values().batchGet(
        spreadsheetId=SPREADSHEET_ID,
        ranges=ranges
    )
    response = requests.execute()

    value_ranges = response.get('valueRanges', [])

    now = services.now_local()
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
    return jsonify({
        "time": current_time,
        "bike_list": bikelist,
    })

@app.route("/addUserHold", methods = ["POST"])
def addUserHold():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email","")
    email_body = data.get("email_body","")
    email = email.strip().lower()
    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error("The email you entered is not currently in the user list")
    new_hold = services.holdUpdate(values[email_idx][4], holdToAdd="L",
                                       tempBanTime=services.osSettings["tempTimeout"])
    target = "UserLog!E" + str(email_idx + 2)
    body = {
        'values': [[new_hold]]
    }
    sheet = services.get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()
    if email_body != "":
        target = "UserLog!H" + str(email_idx + 2)
        body = {
            'values': [[email_body]]
        }
        sheet = services.get_sheets_service().spreadsheets()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID, range=target,
            valueInputOption="USER_ENTERED", body=body).execute()

    services.send_gmail(services.get_gmail_service(),email, services.siteResponse["Emails"]["ManualHold"][0], services.siteResponse["Emails"]["ManualHold"][1] + email_body + services.siteResponse["Emails"]["ManualHold"][2])
    return jsonify({
        "topText": "Success",
        "textbox": "The user: " + email + " has a hold placed on their account"
    })

@app.route("/removeUserHold", methods = ["POST"])
def removeUserHold():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    email = data.get("user_email","")
    email = email.strip().lower()
    RANGE_NAME = "UserLog!A2:G"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")
    user_list = [row[0] for row in values]
    if email in user_list:
        email_idx = user_list.index(email)
    else:
        return error("The email you entered is not currently in the user list")
    new_hold = services.holdUpdate(values[email_idx][4], holdToRemove="L",
                                       tempBanTime=services.osSettings["tempTimeout"])
    if "#" not in new_hold: #This part removes any manual holds
        new_hold = ""

    target = "UserLog!E" + str(email_idx + 2)
    body = {
        'values': [[new_hold]]
    }
    sheet = services.get_sheets_service().spreadsheets()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range=target,
        valueInputOption="USER_ENTERED", body=body).execute()
    services.send_gmail(services.get_gmail_service(),email, services.siteResponse["Emails"]["LHoldRemoval"][0], services.siteResponse["Emails"]["LHoldRemoval"][1])
    return jsonify({
        "topText": "Success",
        "textbox": "The user: " + email + " has the hold removed from their account"
    })


@app.route("/reloadSiteSettings", methods = ["POST"])
def reloadSiteSettings():
    data = request.get_json()
    passCode = int(data.get("loginCode", ""))
    good_code, errormessage = adminLogin(True, passCode)
    if not good_code:
        return error(errormessage)
    services.load_settings()
    return jsonify({
        "topText": "Success at reloading site settings",
        "textbox": "The site has updated with the new OS settings"
    })

def error(message, status=400):
    return jsonify({"error": message}), status


def addUser(email, send_email = True):
    now = services.now_local()
    sheet = services.get_sheets_service().spreadsheets()
    today = date.today()
    account_expiration = date(today.year + (today.month > 5), 5, 31)
    code_expiration = now + timedelta(minutes=30)
    verification_code = randint(100000, 999999)
    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
    message_body = ( services.siteResponse["Emails"]["Verification"][1]+
            "<a href=" + services.osSettings["PageUrl"]+"/?email=" + safe_email + "&code=" + str(verification_code) + ">Verify by clicking here </a>"
                     + services.siteResponse["Emails"]["Verification"][2]+ "<a href="+services.osSettings["PageUrl"]+"/?vp=1>"+services.osSettings["PageUrl"]+"/?vp=1 </a>"
    )
    if send_email:
        services.send_gmail(services.get_gmail_service(),email, services.siteResponse["Emails"]["Verification"][0] + str(verification_code),message_body)

def emailChecker(email,on = services.osSettings["EmailChecking"]):
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

def holdChecker(hold_code, max_amount = services.osSettings["MaxBikes"], tempBan = services.osSettings["TempBan"]):
    hold = False
    topText = ""
    textbox = ""
    if hold_code == "":
        return hold, [topText, textbox]

    if hold_code[0] == "#":
        code = hold_code[1:10]
        if "T" in code:
            now = services.now_local()
            hold_time = hold_code[11:]
            temp = services.timeExtractor(hold_time)
            if temp > now:
                hold = tempBan
                topText = services.siteResponse["Check-out"]["T-hold"][0]
                textbox = services.siteResponse["Check-out"]["T-hold"][1]+" You must wait " + str(int((temp - now).seconds / 60) + 1) + " minutes to check out a new bike"
            # Could add an else here to delete it, but that is a later problem
        if "U" in code:
            position = code.index("U")
            amt_checked_out = int(code[position + 1:position+3], 16)

            if "X" in code:
                position = code.index("X")
                max_amount = max_amount + int(code[position + 1:position+3], 16)
            if amt_checked_out >= max_amount:
                hold = True
                topText = services.siteResponse["Check-out"]["U-hold"][0]
                textbox = services.siteResponse["Check-out"]["U-hold"][1]+" ("+str(max_amount)+") "+services.siteResponse["Check-out"]["U-hold"][2]+" You currently have "+str(int(code[position + 1: position +3], 16)) +" bikes checked out"
        if "P" in code:
            hold = True
            topText = services.siteResponse["Check-out"]["P-hold"][0]
            textbox = services.siteResponse["Check-out"]["P-hold"][1]
        if "L" in code:
            hold = True
            topText = services.siteResponse["Check-out"]["L-hold"][0]
            textbox = services.siteResponse["Check-out"]["L-hold"][1]


    else: #This is if they have a manually added hold on the account
        hold = True
        topText = services.siteResponse["Check-out"]["Other-hold"][0]
        textbox = services.siteResponse["Check-out"]["Other-hold"][1]


    return hold, [topText, textbox]

def driveCheckout(user_info,email_idx, bikeid, bike_idx, helmetid):
    sheet = services.get_sheets_service().spreadsheets()
    #4 Updates to be done
    #Update userlog with times checked out and new hold on account
    #Update bike summary with checked-out
    #Update bike specific log (add a row)
    #Update helmet log
    hold = user_info[4]
    hold = services.holdUpdate(hold, "RU", tempBanTime = services.osSettings["tempTimeout"])
    now = services.now_local()

    requests = [

        # Update user log: +1 ride, update hold
        {
            "updateCells": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
                    "sheetId": services.bike_sheet_dict["Bike" + str(bikeid)],
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
                    "sheetId": services.bike_sheet_dict["Bike" + str(bikeid)],
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
                        "sheetId": services.bike_sheet_dict["HelmetLog"],
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
                        "sheetId": services.bike_sheet_dict["HelmetLog"],
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
        body={
            'requests': requests,
            'includeSpreadsheetInResponse': False,
            'responseIncludeGridData': False
        }
    ).execute()


    
def driveCheckin(user_info,email_idx, bikeid, bike_idx, helmetid, notes, hold_long_term = False):
    sheet = services.get_sheets_service().spreadsheets()
    # 4 Updates to be done
    # Update userlog with times checked out and new hold on account
    # Update bike summary with checked-out
    # Update bike specific log (add a row)
    # Update helmet log


    now = services.now_local()

    requests = [
        {
            "updateCells": {
                "range": {
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
                    "sheetId": services.bike_sheet_dict["Simple Bike Summary"],
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
                    "sheetId": services.bike_sheet_dict["Bike" + str(bikeid)],
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
                    "sheetId": services.bike_sheet_dict["Bike" + str(bikeid)],
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
            hold = services.holdUpdate(hold, holdToAdd="L", tempBanTime = services.osSettings["tempTimeout"])
        hold = services.holdUpdate(hold, holdToRemove="U", tempBanTime = services.osSettings["tempTimeout"])
        requests.extend([
        {
            "updateCells": {
                "range": {
                    "sheetId": services.bike_sheet_dict["UserLog"],
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
                        "sheetId": services.bike_sheet_dict["HelmetLog"],
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
                        "sheetId": services.bike_sheet_dict["HelmetLog"],
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
        body={
            'requests': requests,
            'includeSpreadsheetInResponse': False,
            'responseIncludeGridData': False
        }
    ).execute()



def checkin_async(bike, bciw, issues, helmet, photo_path, email, user_info, email_idx, bike_idx, L_hold):
    try:
        now = services.now_local()
        if photo_path != "":
            contents = "<p> Bike #"+str(bike)+" is checked in as of: <br>"+now.strftime("%m/%d/%Y %H:%M:%S") +".</p><p> Last user was: <br>"+email+"</p> Photo included:"
            services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"][0],"Bikeshare Return Photo Bike #"+str(bike), contents, photo_path)
        #Here is where we can add an option for this to send issues
        if L_hold:
            services.send_gmail(services.get_gmail_service(),email,"Bike #"+str(bike)+services.siteResponse["Emails"]["Return"][0],services.siteResponse["Emails"]["Return"][1])
            services.send_gmail(services.get_gmail_service(),email,services.siteResponse["Emails"]["AutomaticHold"][0],
                       services.siteResponse["Emails"]["AutomaticHold"][1])
            services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"],"Automatic Hold on User Account","<p>User "+email+" did not return their bike within the alloted time and now has a hold and is unable to check out bikes. </p> To remove the hold use the admin panel or manually edit the sheet")
        elif bciw:
            services.send_gmail(services.get_gmail_service(),email,services.siteResponse["Emails"]["ForgottenReturn"][0]+str(bike),
                       services.siteResponse["Emails"]["ForgottenReturn"][1])
            services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"],"Forgotten Bike Return #"+str(bike),"User "+email+" did not return their bike and it was marked as returned by another user")
        else:
            services.send_gmail(services.get_gmail_service(),email,"Bike #"+str(bike)+services.siteResponse["Emails"]["Return"][0],services.siteResponse["Emails"]["Return"][1])
        driveCheckin(user_info,email_idx,bike,bike_idx,helmet,issues,L_hold)
        blank_issue_responses = {
                                    s.strip().lower()
                                    for s in services.osSettings["blankResponses"]
                                    if s is not None
                                } | {""}

        if issues.strip().lower() not in blank_issue_responses:
            #This means there is an issue to be reported and sent to email
            contents = "<p> Reported issue is: <br>" +str(issues)+"<p> Bike #"+str(bike)+" was checked in at: <br>"+now.strftime("%m/%d/%Y %H:%M:%S") +".</p> <p>Last user was: <br>"+email+"</p>"
            if photo_path != "":
                services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"],"Reported Issue with Bike #"+str(bike),contents+ "Photo included",photo_path)
            else:
                services.send_gmail(services.get_gmail_service(),services.osSettings["AdminEmails"],"Reported Issue with Bike #"+str(bike),contents+ "Photo was not included")
    except Exception as e:
        print("Error in checkin_async:", e)




@app.route("/")
def index():
    log_memory()
    return render_template("cow.html")

@app.route("/admin")
def admin():
    log_memory()
    return render_template("admin.html")


@app.route("/health", methods=["GET"])
def health():
    log_memory()
    return "ok", 200

if __name__ == "__main__":
    app.run(host = "0.0.0.0", port=5000,debug=True)