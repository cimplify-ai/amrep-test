from PyPDF2 import PdfReader, PdfWriter
import io
import streamlit as st
import fitz
import datetime
import boto3
import json
import pandas as pd
import re
import os

# st.set_page_config(page_title="Single JSON Viewer", layout="wide")
st.title("📄 Upload a Invoice File")

textract = boto3.client("textract", region_name="us-east-1",
            aws_access_key_id=os.getenv("aws_access_key_id"),
            aws_secret_access_key=os.getenv("aws_secret_access_key") )

uploaded_file = st.file_uploader("Upload a file")

if uploaded_file is not None:
    try:
        def validateTheVendorName(highConfindence, vendorObj):
            if len(highConfindence["ValueDetection"]["Text"].strip()) > vendorObj["vendor_length"]:
                return highConfindence["ValueDetection"]["Text"]
            
            temp = highConfindence["ValueDetection"]["Text"]
            splitTemp = [*temp]

            for vendor in vendorObj["VENDOR_NAME"]:
                regex = re.findall(rf"^{re.escape(highConfindence["ValueDetection"]["Text"].strip())}", vendor["ValueDetection"]["Text"].strip(), re.IGNORECASE)
                vendorSplit = re.findall(r'\b(\w)', vendor["ValueDetection"]["Text"], re.IGNORECASE)

                if bool(regex) and len(highConfindence["ValueDetection"]["Text"].strip()) < len(vendor["ValueDetection"]["Text"].strip()):
                    temp = vendor["ValueDetection"]["Text"].strip()
                
                if len(vendorSplit) >= len(splitTemp) and splitTemp == vendorSplit[:len(splitTemp)]:
                    temp = vendor["ValueDetection"]["Text"].strip()

            temp = re.split(r'^(.*?)\s*(\(\d{4}-\d{2,4}\))', temp)

            if temp[0] == "" :
                return temp[1]
            return temp[0]

        try:
            # file_content = base64.b64decode(data.get("file_content"))
            reader = PdfReader(io.BytesIO(uploaded_file.read()))
            reader = reader.pages[0]
            writer = PdfWriter()
            writer.add_page(reader)

            # Write single-page PDF to a byte stream
            output_stream = io.BytesIO()
            writer.write(output_stream)
            output_stream.seek(0)

            doc = fitz.open(stream=output_stream.read())
            page = doc.load_page(0)
            pixmap = page.get_pixmap(dpi=300)
            img = pixmap.tobytes()

            textract_response = textract.analyze_expense(
                Document={"Bytes": img}
            )

            summary_fields = textract_response["ExpenseDocuments"][0]["SummaryFields"]
            collect_requried_fields = {}
            other_fields = {"OTHER": [], "VENDOR_NAME" : [], "vendor_length": 0}
            fields_list = ["VENDOR_NAME", "INVOICE_RECEIPT_DATE", "INVOICE_RECEIPT_ID"]

            #Phase - I
            for item in summary_fields:
                if item["Type"]["Text"] in fields_list:

                    if item["Type"]["Text"] not in collect_requried_fields.keys(): 
                        collect_requried_fields[item["Type"]["Text"]] = item

                    if collect_requried_fields[item["Type"]["Text"]]["ValueDetection"]["Confidence"] < item["ValueDetection"]["Confidence"]:
                        collect_requried_fields[item["Type"]["Text"]] = item

                if item["Type"]["Text"] == "OTHER":
                    other_fields["OTHER"].append(item)

                if item["Type"]["Text"] == "VENDOR_NAME":
                    other_fields["vendor_length"] = max(other_fields["vendor_length"], len(item["ValueDetection"]["Text"].strip()))
                    item["ValueDetection"]["Text"] = re.split(r'[\n]', item["ValueDetection"]["Text"])[0]
                    other_fields["VENDOR_NAME"].append(item)
            #Phase - II
            if not collect_requried_fields.get("INVOICE_RECEIPT_ID"):
                for item in other_fields["OTHER"]:
                    try: 
                        #invoice Number
                        if bool(re.findall(r"\b(Invoice|Inv|S)\.?\s*(Number|No)\.?\b", item["LabelDetection"]["Text"], re.IGNORECASE)) and "Invoice No" not in collect_requried_fields.keys() :
                            collect_requried_fields["Invoice No"] = item["ValueDetection"]["Text"]
                    
                    except KeyError as error:
                        print("Key Error", error)
            #phase - III
            if not collect_requried_fields.get("INVOICE_RECEIPT_ID"):
                for item in summary_fields:
                    try:
                        #invoice
                        if bool(re.findall(r"\b(Invoice|Inv|S)\.?\s*(Number|No)\.?\b", item["LabelDetection"]["Text"], re.IGNORECASE)) and "Invoice No" not in collect_requried_fields.keys() :
                            collect_requried_fields["Invoice No"] = item["ValueDetection"]["Text"]

                    except KeyError as error:
                        print("key error", error)
            
            collect_requried_fields["Company Name"] = validateTheVendorName(collect_requried_fields["VENDOR_NAME"],  other_fields)

            if collect_requried_fields.get("INVOICE_RECEIPT_ID"):
                collect_requried_fields["Invoice No"] = collect_requried_fields["INVOICE_RECEIPT_ID"]["ValueDetection"]["Text"]
                del collect_requried_fields["INVOICE_RECEIPT_ID"]

            #Invoice Date
            if collect_requried_fields.get("INVOICE_RECEIPT_DATE"):
                collect_requried_fields["Invoice Date"] =  collect_requried_fields["INVOICE_RECEIPT_DATE"]["ValueDetection"]["Text"]
                del collect_requried_fields["INVOICE_RECEIPT_DATE"]
            else:
                collect_requried_fields["Invoice Date"] = datetime.date.today()

            del collect_requried_fields["VENDOR_NAME"]

           
        except KeyError:
            print("error")
        # Load the single JSON object
        # data = json.load(uploaded_file)
        with st.spinner("Processing your file..."):
            if isinstance(collect_requried_fields, dict):
                # Convert to 2-column DataFrame
                df = pd.DataFrame(list(collect_requried_fields.items()), columns=["Key", "Value"])
                st.subheader("🗂️ Results")
                st.dataframe(df, use_container_width=True)
            else:
                st.warning("This tool only supports a single JSON object (not list).")

    except json.JSONDecodeError:
        st.error("The uploaded file is not valid JSON.")
    except Exception as e:
        st.error(f"Unexpected error: {e}")

