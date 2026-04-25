import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import services


load_dotenv("passwords.env")








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
            temp_norm_hours = norm_hours
            if len(row) >= 7:
                extension, hour_count = services.extensionChecker(row[6])
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
                update = services.extensionUpdate(row[6],"M")
                target = "Simple Bike Summary!G" + str(row_idx + 1)
                body = {'values': [[update]]}
                sheet = services.get_sheets_service().spreadsheets()
                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID, range=target,
                    valueInputOption="USER_ENTERED", body=body).execute()
                row[6] = update

    #This section is for updating the lockpage
    lockCodes = {}
    for row in values:
        lockCodes[str(row[0])] = int(row[2])
    RANGE_NAME = "LockLog!A2:B"

    sheet = services.get_sheets_service().spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get("values", "")

    loggedCodes = {}
    for row in values:
        if str(row[0]) in lockCodes.keys() and str(row[0]) not in loggedCodes.keys():
            loggedCodes[str(row[0])] = int(row[1])
        if lockCodes.keys() <= loggedCodes.keys():
            break
    mismatches = []

    for bike_id, code in lockCodes.items():
        if bike_id not in loggedCodes or loggedCodes[bike_id] != code:
            mismatches.append((bike_id,code))
    if mismatches:
        requests = [{

            "insertDimension": {
                "range": {
                    "sheetId": services.bike_sheet_dict["LockLog"],
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 1 + len(mismatches)
                },
                "inheritFromBefore": False
            }

        }]

        now = services.now_local()
        for idx, (ids, code) in enumerate(mismatches):
            requests.extend([{

                "updateCells": {
                    "range": {
                        "sheetId": services.bike_sheet_dict["LockLog"],
                        "startRowIndex": 1 + idx,
                        "endRowIndex": 2 + idx,
                        "startColumnIndex": 0,
                        "endColumnIndex": 3
                    },
                    "rows": [
                        {
                            "values": [
                                {"userEnteredValue": {"numberValue": int(ids)}},
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





if __name__ == "__main__":
    main()
