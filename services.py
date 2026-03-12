import os
import json, base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import tempfile
from email.generator import BytesGenerator
from googleapiclient.http import MediaFileUpload






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
    return build("sheets", "v4", credentials=creds["drive"], cache_discovery=False)
def get_drive_service():
    return build("drive", "v3", credentials=creds["drive"], cache_discovery=False)
def get_gmail_service():
    return build("gmail", "v1", credentials=creds["gmail"], cache_discovery=False)
# ------------------------------------
# GOOGLE DRIVE CLIENT
# ------------------------------------
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]


LOCAL_TZ = ZoneInfo("America/Chicago")

def now_local():
    return datetime.now(LOCAL_TZ)



siteResponse = {}
osSettings = {}
bike_sheet_dict = {}
qr_codes_to_bike_id = {}
def load_settings():
    bike_sheet_dict.clear()
    spreadsheet = get_sheets_service().spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    for sheet in spreadsheet["sheets"]:
        props = sheet["properties"]
        bike_sheet_dict.update({props["title"]: props["sheetId"]})
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

    qr_codes_to_bike_id.clear()
    RANGE_NAME = "BikeWebpageIDs!A2:B"
    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    values = result.get("values", [])

    for row in values:
        if len(row) > 1:
            qr_codes_to_bike_id[row[0]] = int(row[1])

    #This is for the OS settings page, this is a bit less automatic and more manual
    osSettings.clear()
    RANGE_NAME = "osSettings"

    sheet = get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    values = result.get("values", "")
    for row in values:
        osSettings[row[0]] = row[1:]
        if len(osSettings[row[0]]) == 1:
            osSettings[row[0]] = osSettings[row[0]][0]

    if isinstance(osSettings["AdminEmails"], str):
        osSettings["AdminEmails"] = [osSettings["AdminEmails"]]


    osSettings["HelmetList"] = [int(x) for x in osSettings["HelmetList"]]
    osSettings["adminLoginSafety"] = int(osSettings["adminLoginSafety"]) == 1
    osSettings["tempTimeout"] = int(osSettings["tempTimeout"])
    osSettings["checkOutLength"] = int(osSettings["checkOutLength"])
    osSettings["TempBan"] = int(osSettings["TempBan"]) == 1
    osSettings["EmailChecking"] = int(osSettings["EmailChecking"]) == 1
    osSettings["MaxBikes"] = int(osSettings["MaxBikes"])
    osSettings["paymentRequirement"] = int(osSettings["paymentRequirement"]) == 1
    osSettings["overdueHoldLength"] = int(osSettings["overdueHoldLength"])


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




def send_gmail(service, to, subject, html_contents, attachments=None):
    if attachments is None:
        attachments = []
    elif isinstance(attachments, str):
        attachments = [attachments]
    if isinstance(to, (list, tuple, set)):
        to = ", ".join(to)

    # 1. Build the Root message
    msg = MIMEMultipart()
    msg["To"] = to
    msg["From"] = "me"
    msg["Subject"] = subject
    msg.attach(MIMEText(html_contents, "html"))

    # 2. Process Attachments
    for path in attachments:
        content_type, encoding = mimetypes.guess_type(path)
        if content_type is None:
            content_type = "application/octet-stream"

        main_type, sub_type = content_type.split("/", 1)

        part = MIMEBase(main_type, sub_type)
        with open(path, "rb") as f:
            part.set_payload(f.read())
        try:
            os.remove(path)
        except OSError as e:
            print(f"Error deleting {path}: {e}")

        encoders.encode_base64(part)
        filename = path.split("/")[-1]
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        msg.attach(part)

    # 3. Stream the message to a temporary file instead of memory
    # delete=False is required for Windows compatibility when passing the file to MediaFileUpload
    with tempfile.NamedTemporaryFile(delete=False) as temp_msg_file:
        temp_file_path = temp_msg_file.name
        generator = BytesGenerator(temp_msg_file)
        generator.flatten(msg)

    try:
        # 4. Stream the file directly to the Gmail API
        media = MediaFileUpload(
            temp_file_path,
            mimetype='message/rfc822',
            resumable=True  # Enables chunked uploading to save memory
        )

        service.users().messages().send(
            userId="me",
            media_body=media
        ).execute()

    finally:
        # 5. Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def holdUpdate(currentHold, holdToAdd = "", holdToRemove = "", tempBanTime = None):
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
        return f"#{codeString:<10}{timeString}"
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