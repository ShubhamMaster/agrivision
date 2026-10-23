"""
AgriVision — multilingual support (English, Marathi, Hindi).

Why a dictionary and not Flask-Babel
------------------------------------
The usual answer is Flask-Babel with gettext .po/.mo catalogues. It was not
used here for three reasons that matter to this project:

  1. .mo files are compiled artefacts. They need `pybabel compile` after every
     edit, and a stale or missing .mo silently falls back to English — a
     confusing failure in a project someone else has to run.
  2. AgriVision is required to run with no network and no build step. Plain
     Python dictionaries are imported like any other module.
  3. Adding a string here means adding one line to two dictionaries, which a
     student maintaining this can do without learning gettext tooling.

For a production deployment with professional translators, Flask-Babel is the
right tool, because .po files are what translation agencies work in. That is
noted in docs/13_multilingual_and_onboarding.md.

The key is the English text
---------------------------
    t("Marketplace")  ->  "बाजारपेठ"  in Marathi

Using the English string as the key means an untranslated phrase renders as
readable English instead of a raw identifier like `nav.marketplace`. A missing
translation degrades to something the user can still act on.

Interpolation uses str.format:

    t("Showing {n} lots", n=14)
"""

from __future__ import annotations

import re

from flask import g, has_request_context, request, session

# ----------------------------------------------------------------------
# Supported languages
# ----------------------------------------------------------------------
LANGUAGES = {
    "en": {"name": "English", "native": "English", "script": "latin"},
    "mr": {"name": "Marathi", "native": "मराठी", "script": "devanagari"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "script": "devanagari"},
}
DEFAULT_LANGUAGE = "en"


# ======================================================================
# MARATHI
# ======================================================================
MR = {
    # --- navigation and chrome ---------------------------------------
    "Dashboard": "डॅशबोर्ड",
    "My Crops": "माझी पिके",
    "Buyer Requirements": "खरेदीदारांच्या मागण्या",
    "Marketplace": "बाजारपेठ",
    "My Requirements": "माझ्या मागण्या",
    "Deals": "व्यवहार",
    "Market Insights": "बाजार माहिती",
    "How it works": "हे कसे चालते",
    "Log in": "लॉग इन",
    "Log out": "लॉग आउट",
    "Register free": "मोफत नोंदणी",
    "Profile & settings": "प्रोफाइल आणि सेटिंग्ज",
    "Notifications": "सूचना",
    "Language": "भाषा",
    "Home": "मुख्यपृष्ठ",
    "Platform": "प्लॅटफॉर्म",
    "AI modules": "एआय मॉड्यूल्स",
    "Farmer": "शेतकरी",
    "Buyer": "खरेदीदार",
    "farmer": "शेतकरी",
    "buyer": "खरेदीदार",

    # --- common words -------------------------------------------------
    "Crop": "पीक",
    "Crops": "पिके",
    "Variety": "वाण",
    "Quantity": "प्रमाण",
    "Price": "दर",
    "Grade": "प्रत",
    "Quality": "गुणवत्ता",
    "Location": "ठिकाण",
    "District": "जिल्हा",
    "Taluka / Tehsil": "तालुका",
    "State": "राज्य",
    "PIN code": "पिन कोड",
    "Market": "बाजार",
    "quintal": "क्विंटल",
    "Status": "स्थिती",
    "Available": "उपलब्ध",
    "available": "उपलब्ध",
    "reserved": "राखीव",
    "sold": "विकले",
    "withdrawn": "मागे घेतले",
    "Organic": "सेंद्रिय",
    "Certified": "प्रमाणित",
    "Certificate pending": "प्रमाणपत्र प्रलंबित",
    "Certificate rejected": "प्रमाणपत्र नाकारले",
    "No certificate needed": "प्रमाणपत्राची गरज नाही",
    "Save changes": "बदल जतन करा",
    "Cancel": "रद्द करा",
    "Delete": "हटवा",
    "Edit": "संपादित करा",
    "View all": "सर्व पहा",
    "See all": "सर्व पहा",
    "Manage all": "सर्व व्यवस्थापित करा",
    "Apply filters": "फिल्टर लावा",
    "Clear all": "सर्व साफ करा",
    "Filters": "फिल्टर",
    "Sort by": "क्रमवारी",
    "Newest first": "नवीनतम प्रथम",
    "Back to marketplace": "बाजारपेठेकडे परत",
    "My crops": "माझी पिके",
    "Send": "पाठवा",
    "Compare": "तुलना करा",
    "just now": "आत्ताच",
    "Not graded": "प्रत ठरलेली नाही",
    "Nothing here": "येथे काहीही नाही",
    "All crops": "सर्व पिके",
    "Any grade": "कोणतीही प्रत",
    "any": "कोणतेही",
    "no limit": "मर्यादा नाही",
    "All": "सर्व",
    "Open": "सुरू",
    "Closed": "बंद",

    # --- crops ---------------------------------------------------------
    "Grapes": "द्राक्ष",
    "Pomegranate": "डाळिंब",
    "Mango": "आंबा",
    "Banana": "केळी",
    "Tomato": "टोमॅटो",
    "Onion": "कांदा",
    "Potato": "बटाटा",
    "Wheat": "गहू",
    "Rice": "तांदूळ",
    "Maize": "मका",
    "Soybean": "सोयाबीन",
    "Cotton": "कापूस",
    "Sugarcane": "ऊस",
    "Chilli": "मिरची",

    # --- home page ------------------------------------------------------
    "Sell your harvest at the price it deserves.":
        "तुमच्या मालाला योग्य तो भाव मिळवा.",
    "AgriVision connects farmers directly with buyers — no middlemen. Upload a "
    "photo of your crop and our AI grades its quality, suggests a fair price from "
    "live regional trends, predicts demand, and verifies your quality certificates.":
        "अ‍ॅग्रिव्हिजन शेतकऱ्यांना थेट खरेदीदारांशी जोडते — दलालांशिवाय. तुमच्या पिकाचा "
        "फोटो अपलोड करा; आमची एआय प्रणाली गुणवत्ता ठरवते, स्थानिक बाजारभावावरून योग्य दर "
        "सुचवते, मागणीचा अंदाज देते आणि तुमची प्रमाणपत्रे तपासते.",
    "I am a Farmer": "मी शेतकरी आहे",
    "I am a Buyer": "मी खरेदीदार आहे",
    "Go to my dashboard": "माझ्या डॅशबोर्डवर जा",
    "Farmers": "शेतकरी",
    "Buyers": "खरेदीदार",
    "Live listings": "सुरू असलेल्या नोंदी",
    "Open requirements": "सुरू असलेल्या मागण्या",
    "Deals struck": "झालेले व्यवहार",
    "Quintal available": "उपलब्ध क्विंटल",
    "How AgriVision works": "अ‍ॅग्रिव्हिजन कसे चालते",
    "Photograph the lot": "मालाचा फोटो काढा",
    "The farmer uploads photos, quantity and location. No paperwork, no agent visit.":
        "शेतकरी फोटो, प्रमाण आणि ठिकाण नोंदवतो. कागदपत्रे नाहीत, दलालाची गरज नाही.",
    "AI grades and prices it": "एआय प्रत आणि दर ठरवते",
    "Computer vision scores colour, uniformity, defects and size, then a price "
    "band is computed from district mandi trends.":
        "संगणक दृष्टी रंग, एकसारखेपणा, दोष आणि आकार तपासते, आणि जिल्ह्याच्या बाजारभावावरून "
        "योग्य दराची श्रेणी काढते.",
    "Certificates verified": "प्रमाणपत्रे तपासली जातात",
    "For grapes and other export crops the certificate is read by OCR and checked "
    "against the issuing authority's format and validity.":
        "द्राक्षासारख्या निर्यात पिकांसाठी प्रमाणपत्र ओसीआरने वाचले जाते आणि जारी करणाऱ्या "
        "संस्थेच्या नमुन्याशी व मुदतीशी तपासले जाते.",
    "Deal directly": "थेट व्यवहार करा",
    "Buyers post requirements or send buying requests. Both sides negotiate in one "
    "thread and close the trade.":
        "खरेदीदार मागणी नोंदवतात किंवा खरेदी विनंती पाठवतात. दोन्ही बाजू एकाच ठिकाणी बोलणी "
        "करून व्यवहार पूर्ण करतात.",
    "Top-graded lots on the platform": "प्लॅटफॉर्मवरील सर्वोत्तम प्रतीचा माल",
    "Buyers are looking for": "खरेदीदारांना हवे आहे",
    "Grade {g} or better": "प्रत {g} किंवा त्याहून चांगली",

    # --- auth ------------------------------------------------------------
    "Create your free account": "तुमचे मोफत खाते तयार करा",
    "AgriVision keeps the two sides of the market separate. Choose the side you "
    "are on — each one gets its own dashboard and tools.":
        "अ‍ॅग्रिव्हिजनमध्ये बाजाराच्या दोन्ही बाजू वेगळ्या असतात. तुम्ही कोणत्या बाजूचे आहात ते "
        "निवडा — प्रत्येकाला स्वतःचा डॅशबोर्ड आणि साधने मिळतात.",
    "Register as Farmer": "शेतकरी म्हणून नोंदणी करा",
    "Register as Buyer": "खरेदीदार म्हणून नोंदणी करा",
    "List your crops, get an AI quality grade and a fair price band, see what "
    "buyers are asking for, and sell directly.":
        "तुमची पिके नोंदवा, एआयकडून गुणवत्तेची प्रत आणि योग्य दराची श्रेणी मिळवा, खरेदीदारांच्या "
        "मागण्या पहा आणि थेट विक्री करा.",
    "Post what you need, browse graded lots with verified quality, compare them "
    "side by side and buy straight from the farmer.":
        "तुम्हाला काय हवे ते नोंदवा, प्रत ठरलेला माल पहा, त्यांची तुलना करा आणि थेट शेतकऱ्याकडून "
        "खरेदी करा.",
    "Already registered?": "आधीच नोंदणी केली आहे?",
    "Log in here": "येथे लॉग इन करा",
    "Welcome back": "पुन्हा स्वागत आहे",
    "Log in to your AgriVision account": "तुमच्या अ‍ॅग्रिव्हिजन खात्यात लॉग इन करा",
    "Email or mobile number": "ईमेल किंवा मोबाइल नंबर",
    "Password": "पासवर्ड",
    "Keep me logged in": "मला लॉग इन ठेवा",
    "New to AgriVision?": "अ‍ॅग्रिव्हिजनवर नवीन आहात?",
    "Create a free account": "मोफत खाते तयार करा",
    "Your details": "तुमची माहिती",
    "Full name": "पूर्ण नाव",
    "Mobile number": "मोबाइल नंबर",
    "Email address": "ईमेल पत्ता",
    "Farm size (acres)": "शेतीचे क्षेत्र (एकर)",
    "Company / firm name": "कंपनी / फर्मचे नाव",
    "Type of buyer": "खरेदीदाराचा प्रकार",
    "GST number": "जीएसटी क्रमांक",
    "Security": "सुरक्षा",
    "Confirm password": "पासवर्डची खात्री करा",
    "Create account": "खाते तयार करा",
    "Change account type": "खात्याचा प्रकार बदला",
    "At least 6 characters.": "किमान ६ अक्षरे.",
    "Your district decides which mandi prices and demand forecasts you are shown, "
    "so please fill it accurately.":
        "तुमचा जिल्हा ठरवतो की कोणते बाजारभाव आणि मागणीचे अंदाज तुम्हाला दिसतील, त्यामुळे तो "
        "अचूक भरा.",
    "Account details": "खात्याची माहिती",
    "Change password": "पासवर्ड बदला",
    "Current password": "सध्याचा पासवर्ड",
    "New password": "नवीन पासवर्ड",
    "Confirm new password": "नवीन पासवर्डची खात्री करा",
    "Update password": "पासवर्ड बदला",
    "Member since": "सदस्य असल्यापासून",

    # --- farmer -----------------------------------------------------------
    "List a new crop": "नवीन पीक नोंदवा",
    "List a crop": "पीक नोंदवा",
    "My crop listings": "माझ्या पिकांच्या नोंदी",
    "Quintal on sale": "विक्रीसाठी क्विंटल",
    "Potential value": "अपेक्षित रक्कम",
    "Pending requests": "प्रलंबित विनंत्या",
    "Accepted deals": "स्वीकारलेले व्यवहार",
    "Listing views": "नोंदी पाहिल्या",
    "Buying requests waiting for you": "तुमच्यासाठी प्रलंबित खरेदी विनंत्या",
    "My recent listings": "माझ्या अलीकडील नोंदी",
    "Buyer requirements that match your crops": "तुमच्या पिकांशी जुळणाऱ्या मागण्या",
    "Demand in {place}": "{place} मधील मागणी",
    "Full market insights": "संपूर्ण बाजार माहिती",
    "Tips for a better grade": "चांगली प्रत मिळवण्यासाठी सूचना",
    "Shoot in daylight, never under a tube-light.":
        "दिवसाच्या उजेडात फोटो काढा, ट्यूबलाइटखाली नको.",
    "Fill the frame with the produce — no sky, no floor.":
        "फोटोमध्ये फक्त माल दिसू द्या — आकाश किंवा जमीन नको.",
    "Spread the lot out; overlapping fruit hides defects and lowers the size score.":
        "माल पसरवून ठेवा; एकावर एक ठेवलेली फळे दोष लपवतात आणि आकाराचा गुण कमी करतात.",
    "Upload 3–5 photos from different sides. The system uses the weakest side too.":
        "वेगवेगळ्या बाजूंनी ३–५ फोटो अपलोड करा. प्रणाली सर्वात कमकुवत बाजूही पाहते.",
    "Sort out damaged pieces before photographing — uniformity is 22% of the score.":
        "फोटो काढण्यापूर्वी खराब माल बाजूला काढा — एकसारखेपणा गुणांच्या २२% आहे.",
    "What are you selling?": "तुम्ही काय विकत आहात?",
    "Where is the lot?": "माल कुठे आहे?",
    "Photos for AI grading": "एआय प्रतवारीसाठी फोटो",
    "Your price": "तुमचा दर",
    "Expected price (₹ per quintal)": "अपेक्षित दर (₹ प्रति क्विंटल)",
    "Harvest date": "काढणीची तारीख",
    "Organically grown": "सेंद्रिय पद्धतीने पिकवलेले",
    "Nearest market / APMC": "जवळचा बाजार / कृषी उत्पन्न बाजार समिती",
    "Description / notes for buyers": "खरेदीदारांसाठी माहिती",
    "AI price assistant": "एआय दर सहाय्यक",
    "Choose a crop to see the AI price suggestion.":
        "एआयने सुचवलेला दर पाहण्यासाठी पीक निवडा.",
    "AI quality report": "एआय गुणवत्ता अहवाल",
    "Re-run AI grading": "एआय प्रतवारी पुन्हा चालवा",
    "Photos": "फोटो",
    "Quality certificates": "गुणवत्ता प्रमाणपत्रे",
    "Upload certificate": "प्रमाणपत्र अपलोड करा",
    "Requests on this lot": "या मालावरील विनंत्या",
    "Pricing": "दर",
    "Your asking price": "तुमचा मागितलेला दर",
    "Lot value": "मालाची एकूण किंमत",
    "AI fair price band": "एआय योग्य दर श्रेणी",
    "Demand & market": "मागणी आणि बाजार",
    "Lot details": "मालाची माहिती",
    "What buyers are looking for": "खरेदीदारांना काय हवे आहे",
    "Offer": "देऊ करा",
    "Send offer": "ऑफर पाठवा",

    # --- buyer -------------------------------------------------------------
    "Post a requirement": "मागणी नोंदवा",
    "Browse marketplace": "बाजारपेठ पहा",
    "Requests sent": "पाठवलेल्या विनंत्या",
    "Offers to review": "पाहण्यासाठी ऑफर",
    "Deals closed": "पूर्ण झालेले व्यवहार",
    "Committed value": "ठरलेली रक्कम",
    "Total requirements": "एकूण मागण्या",
    "Farmer offers waiting for your answer": "तुमच्या उत्तराची वाट पाहणाऱ्या ऑफर",
    "Lots that match your open requirements": "तुमच्या मागण्यांशी जुळणारा माल",
    "Minimum grade": "किमान प्रत",
    "Maximum price (₹/quintal)": "कमाल दर (₹/क्विंटल)",
    "Minimum quantity (quintal)": "किमान प्रमाण (क्विंटल)",
    "Organic only": "फक्त सेंद्रिय",
    "Certificate verified": "प्रमाणपत्र तपासलेले",
    "Send a buying request": "खरेदी विनंती पाठवा",
    "Send buying request": "खरेदी विनंती पाठवा",
    "Your offer (₹/quintal)": "तुमची ऑफर (₹/क्विंटल)",
    "Message to the farmer": "शेतकऱ्याला संदेश",
    "The seller": "विक्रेता",
    "Market context": "बाजाराची स्थिती",
    "Independent AI quality assessment": "स्वतंत्र एआय गुणवत्ता तपासणी",
    "Side-by-side comparison": "बाजूबाजूला तुलना",
    "Value score": "मूल्य गुण",
    "Best value": "सर्वोत्तम मूल्य",
    "View & request": "पहा आणि विनंती करा",
    "Certificates": "प्रमाणपत्रे",

    # --- deals ---------------------------------------------------------------
    "Received": "मिळालेल्या",
    "Sent": "पाठवलेल्या",
    "pending": "प्रलंबित",
    "accepted": "स्वीकारले",
    "rejected": "नाकारले",
    "cancelled": "रद्द केले",
    "completed": "पूर्ण झाले",
    "Terms on the table": "ठरलेल्या अटी",
    "Price offered": "देऊ केलेला दर",
    "Total value": "एकूण रक्कम",
    "Conversation": "संभाषण",
    "Write a message…": "संदेश लिहा…",
    "Your decision": "तुमचा निर्णय",
    "Decline": "नाकारा",
    "Mark as completed": "पूर्ण झाले म्हणून नोंदवा",
    "Contact details": "संपर्क माहिती",
    "The lot": "माल",

    # --- insights --------------------------------------------------------------
    "Demand ranking for {place}": "{place} साठी मागणीचा क्रम",
    "Price history and 6-week forecast": "दराचा इतिहास आणि ६ आठवड्यांचा अंदाज",
    "Six-week outlook": "सहा आठवड्यांचा अंदाज",
    "What is driving demand": "मागणी कशामुळे आहे",
    "On AgriVision right now": "सध्या अ‍ॅग्रिव्हिजनवर",
    "lots listed": "नोंदवलेला माल",
    "open requirements": "सुरू मागण्या",
    "Update": "अद्ययावत करा",

    # --- onboarding --------------------------------------------------------------
    "Welcome to AgriVision": "अ‍ॅग्रिव्हिजनमध्ये स्वागत आहे",
    "Skip for now": "आता वगळा",
    "Start using AgriVision": "अ‍ॅग्रिव्हिजन वापरायला सुरुवात करा",
    "You can open this guide again any time from the menu under your name.":
        "तुमच्या नावाखालील मेनूमधून ही मार्गदर्शिका कधीही पुन्हा उघडता येईल.",
    "How to use AgriVision": "अ‍ॅग्रिव्हिजन कसे वापरावे",
    "Quick start guide": "झटपट मार्गदर्शिका",
    "Back to dashboard": "डॅशबोर्डवर परत",
    "List my first crop": "माझे पहिले पीक नोंदवा",
    "Browse the marketplace": "बाजारपेठ पहा",
    "Four things to know before you list your first crop. It takes a minute to read.":
        "पहिले पीक नोंदवण्यापूर्वी चार गोष्टी समजून घ्या. वाचायला एक मिनिट लागेल.",
    "Four things to know before you buy your first lot. It takes a minute to read.":
        "पहिला माल खरेदी करण्यापूर्वी चार गोष्टी समजून घ्या. वाचायला एक मिनिट लागेल.",

    # farmer guide steps
    "Photograph your crop": "तुमच्या पिकाचा फोटो काढा",
    "Spread the lot out in daylight and take 3 to 5 photos from different sides, "
    "filling the frame with the produce. The clearer the photo, the fairer the grade.":
        "दिवसाच्या उजेडात माल पसरवा आणि वेगवेगळ्या बाजूंनी ३ ते ५ फोटो काढा; फोटोत फक्त माल "
        "दिसू द्या. फोटो जितका स्पष्ट, प्रत तितकी अचूक.",
    "Let the AI grade and price it": "एआयला प्रत आणि दर ठरवू द्या",
    "Colour, uniformity, blemishes and size are scored automatically into a Grade A, "
    "B or C. A fair price band is then worked out from the last 45 days of your own "
    "district's mandi rates.":
        "रंग, एकसारखेपणा, डाग आणि आकार यावरून आपोआप अ, ब किंवा क प्रत ठरते. त्यानंतर तुमच्याच "
        "जिल्ह्यातील गेल्या ४५ दिवसांच्या बाजारभावावरून योग्य दराची श्रेणी काढली जाते.",
    "Upload your certificate": "तुमचे प्रमाणपत्र अपलोड करा",
    "Grapes, pomegranate, mango and banana need a quality certificate before they can "
    "be sold here. Photograph the whole page and it is checked and verified in seconds.":
        "द्राक्ष, डाळिंब, आंबा आणि केळी विकण्यासाठी गुणवत्ता प्रमाणपत्र आवश्यक आहे. संपूर्ण पानाचा "
        "फोटो काढा; काही सेकंदांत ते तपासले आणि मंजूर केले जाते.",
    "Answer buyers directly": "खरेदीदारांना थेट उत्तर द्या",
    "Buyers send you requests, and you can offer your lot against what they have asked "
    "for. Accept, decline or negotiate — contact details are shared once you accept.":
        "खरेदीदार तुम्हाला विनंती पाठवतात आणि तुम्ही त्यांच्या मागणीसाठी तुमचा माल देऊ करू शकता. "
        "स्वीकारा, नाकारा किंवा बोलणी करा — स्वीकारल्यावर संपर्क माहिती दिली जाते.",

    # buyer guide steps
    "Post what you need": "तुम्हाला काय हवे ते नोंदवा",
    "Give the crop, quantity, minimum grade and your price range. Every farmer growing "
    "that crop is notified, and matching lots appear on your requirement page.":
        "पीक, प्रमाण, किमान प्रत आणि दराची श्रेणी नोंदवा. ते पीक घेणाऱ्या प्रत्येक शेतकऱ्याला सूचना "
        "जाते आणि जुळणारा माल तुमच्या मागणीच्या पानावर दिसतो.",
    "Filter on grade, not on guesswork": "अंदाजाने नव्हे, प्रतीनुसार निवडा",
    "Every lot carries an independent AI quality grade and, where it applies, a "
    "verified certificate. Filter on both so you only look at lots worth travelling for.":
        "प्रत्येक मालाला स्वतंत्र एआय गुणवत्ता प्रत असते आणि लागू असेल तेथे तपासलेले प्रमाणपत्रही. "
        "दोन्हींवर फिल्टर लावा म्हणजे पाहण्यासारखाच माल तुमच्यासमोर येईल.",
    "Check the fair price band": "योग्य दराची श्रेणी तपासा",
    "Each lot shows the fair price band for its grade and district alongside the asking "
    "price, so you can see at a glance whether there is room to negotiate.":
        "प्रत्येक मालासोबत त्याच्या प्रतीसाठी आणि जिल्ह्यासाठी योग्य दराची श्रेणी मागितलेल्या दरासोबत "
        "दिसते, त्यामुळे बोलणी करायला जागा आहे का हे लगेच कळते.",
    "Compare, then buy direct": "तुलना करा, मग थेट खरेदी करा",
    "Put up to four lots side by side and compare quality per rupee. Send a buying "
    "request straight to the farmer — no commission agent in between.":
        "चार मालांची बाजूबाजूला तुलना करा आणि प्रति रुपया गुणवत्ता पहा. थेट शेतकऱ्याला खरेदी "
        "विनंती पाठवा — मध्ये कोणताही दलाल नाही.",

    # --- footer ----------------------------------------------------------------------
    "A direct farmer-to-buyer marketplace with AI crop grading, price intelligence, "
    "demand prediction and certificate verification — built to cut out the middlemen.":
        "एआय प्रतवारी, दर माहिती, मागणीचा अंदाज आणि प्रमाणपत्र तपासणी असलेली थेट शेतकरी-ते-"
        "खरेदीदार बाजारपेठ — दलाल टाळण्यासाठी बनवलेली.",
    "Computer-vision crop grading": "संगणक दृष्टीद्वारे प्रतवारी",
    "Regional price recommendation": "प्रादेशिक दर शिफारस",
    "Demand index & 6-week forecast": "मागणी निर्देशांक आणि ६ आठवड्यांचा अंदाज",
    "OCMR certificate verification": "ओसीएमआर प्रमाणपत्र तपासणी",
    "Showing {n} lots": "{n} माल दाखवत आहे",
    "{n} lots available": "{n} माल उपलब्ध",
    "Can't find it? Post a requirement": "सापडत नाही? मागणी नोंदवा",
    "{n} min ago": "{n} मिनिटांपूर्वी",
    "{n} hr ago": "{n} तासांपूर्वी",
    "{n} days ago": "{n} दिवसांपूर्वी",
    "yesterday": "काल",

    # --- demand labels and buyer types (passed to t() dynamically) ----------------
    "Strong demand": "जोरदार मागणी",
    "Firm demand": "स्थिर मागणी",
    "Balanced market": "संतुलित बाजार",
    "Soft demand": "मंद मागणी",
    "Weak demand": "कमकुवत मागणी",
    "Trader": "व्यापारी",
    "Exporter": "निर्यातदार",
    "Retailer / Mall": "किरकोळ विक्रेता / मॉल",
    "Food Processor": "अन्न प्रक्रिया उद्योग",
    "FPO / Co-operative": "शेतकरी उत्पादक कंपनी / सहकारी संस्था",
    "Hotel / Restaurant": "हॉटेल / उपाहारगृह",
    "Price: low to high": "दर: कमी ते जास्त",
    "Price: high to low": "दर: जास्त ते कमी",
    "Best quality first": "सर्वोत्तम प्रत प्रथम",
    "Largest lot first": "सर्वात मोठा माल प्रथम",

    # --- empty states and metric labels -------------------------------------------
    "Colour match": "रंग जुळवणी",
    "Colour match for ": "रंग जुळवणी — ",
    "Uniformity": "एकसारखेपणा",
    "Uniformity across the lot": "संपूर्ण मालातील एकसारखेपणा",
    "Freedom from defects": "दोषमुक्तता",
    "Unit size & consistency": "आकार आणि सातत्य",
    "No listings yet": "अजून कोणतीही नोंद नाही",
    "List your first crop lot and the AI will grade it instantly.":
        "तुमचे पहिले पीक नोंदवा; एआय लगेच त्याची प्रत ठरवेल.",
    "No listings with this status.": "या स्थितीत कोणतीही नोंद नाही.",
    "No requirements found": "कोणतीही मागणी सापडली नाही",
    "No buyer requirement matches this filter right now.":
        "सध्या या फिल्टरशी जुळणारी कोणतीही मागणी नाही.",
    "No requirements posted": "कोणतीही मागणी नोंदवलेली नाही",
    "Tell the platform what you need and matching farmers are notified automatically.":
        "तुम्हाला काय हवे ते नोंदवा; जुळणाऱ्या शेतकऱ्यांना आपोआप सूचना जाईल.",
    "No lots match these filters": "या फिल्टरशी जुळणारा माल नाही",
    "Try widening the grade, price or district filter — or post a requirement so farmers come to you.":
        "प्रत, दर किंवा जिल्ह्याचा फिल्टर थोडा सैल करा — किंवा मागणी नोंदवा म्हणजे शेतकरी तुमच्याकडे येतील.",
    "Nothing to compare": "तुलना करण्यासारखे काही नाही",
    "Tick the comparison box on two or more lots in the marketplace.":
        "बाजारपेठेत दोन किंवा अधिक मालांवरील तुलना चौकट निवडा.",
    "Nothing yet": "अजून काहीही नाही",
    "Requests, offers and messages will appear here.":
        "विनंत्या, ऑफर आणि संदेश इथे दिसतील.",
    "Requests and offers will appear in this inbox.":
        "विनंत्या आणि ऑफर या इनबॉक्समध्ये दिसतील.",
    # --- added when template coverage was completed ---------------------
    "1 · Crop quality grading (computer vision)": "१ · पीक गुणवत्ता प्रतवारी (संगणक दृष्टी)",
    "1 · Photograph the lot": "१ · लॉटचा फोटो काढा",
    "2 · AI grades and prices it": "२ · AI प्रतवारी व दर ठरवते",
    "2 · Price recommendation": "२ · दर शिफारस",
    "3 · Certificates verified": "३ · प्रमाणपत्र पडताळणी",
    "3 · Demand prediction": "३ · मागणी अंदाज",
    "4 · Deal directly": "४ · थेट व्यवहार",
    "4 · OCMR certificate verification": "४ · OCMR प्रमाणपत्र पडताळणी",
    "A 0–100 demand index fuses four independent signals:": "०–१०० मागणी निर्देशांक चार स्वतंत्र संकेत एकत्र करतो:",
    "A quality score and Grade A/B/C are assigned to the lot.": "लॉटला गुणवत्ता गुण व प्रत A/B/C दिली जाते.",
    "A ten-check rule engine producing a confidence score.": "दहा तपासण्यांचे नियम-इंजिन विश्वास गुण तयार करते.",
    "Why this matters.": "हे का महत्त्वाचे आहे.",
    "AI band": "AI पट्टा",
    "AI fair band": "AI रास्त दर पट्टा",
    "AI grade": "AI प्रत",
    "AI grading from a photo": "फोटोवरून AI प्रतवारी",
    "AI quality grade": "AI गुणवत्ता प्रत",
    "Above band": "पट्ट्याच्या वर",
    "Above the fair band": "रास्त दर पट्ट्याच्या वर",
    "Below band": "पट्ट्याच्या खाली",
    "Below the fair band": "रास्त दर पट्ट्याच्या खाली",
    "Inside the fair band": "रास्त दर पट्ट्यात",
    "Within band": "पट्ट्यात",
    "Under fair band": "रास्त दरापेक्षा कमी",
    "Asking price": "मागितलेला दर",
    "Recommended": "शिफारस",
    "Fair price today (Grade B)": "आजचा रास्त दर (प्रत B)",
    "Fair-price check on every lot": "प्रत्येक लॉटवर रास्त दर तपासणी",
    "Grade A lots command about 18% more, Grade C about 18% less than this band.": "प्रत A चे लॉट या पट्ट्यापेक्षा सुमारे १८% जास्त, तर प्रत C सुमारे १८% कमी दर मिळवतात.",
    "Grade A only": "फक्त प्रत A",
    "Grade B or better": "प्रत B किंवा वरची",
    "Grade C or better": "प्रत C किंवा वरची",
    "minimum grade": "किमान प्रत",
    "Minimum acceptable grade": "किमान स्वीकार्य प्रत",
    "Colour": "रंग",
    "Colour match for": "यासाठी रंग जुळवणी —",
    "Colour score": "रंग गुण",
    "Defects": "दोष",
    "Defect-free score": "दोषमुक्त गुण",
    "Uniformity score": "एकसारखेपणा गुण",
    "Size": "आकार",
    "value score": "मूल्य गुण",
    "Attribute": "गुणधर्म",
    "per quintal": "प्रति क्विंटल",
    "All deals": "सर्व व्यवहार",
    "Browse all": "सर्व पहा",
    "browse the marketplace": "बाजारपेठ पहा",
    "Market insights": "बाजार माहिती",
    "Filter by grade, price and certificate": "प्रत, दर व प्रमाणपत्रानुसार गाळा",
    "Side-by-side lot comparison": "लॉटची शेजारी-शेजारी तुलना",
    "Compare now": "आता तुलना करा",
    "Compare up to four lots side by side before you commit.": "ठरवण्याआधी चार लॉटपर्यंत शेजारी-शेजारी तुलना करा.",
    "lot(s) selected for comparison (max 4)": "तुलनेसाठी निवडलेले लॉट (कमाल ४)",
    "Clear": "साफ करा",
    "Lots are ordered by": "लॉट क्रमाने लावले आहेत —",
    "Lot": "लॉट",
    "Lot quantity": "लॉट प्रमाण",
    "Lot status": "लॉट स्थिती",
    "Qty": "प्रमाण",
    "Quantity (q)": "प्रमाण (क्विं)",
    "Quantity (quintal)": "प्रमाण (क्विंटल)",
    "Quantity available": "उपलब्ध प्रमाण",
    "My price": "माझा दर",
    "Views": "पाहण्या",
    "Listed": "नोंदवले",
    "Posted": "प्रसिद्ध केले",
    "Manage": "व्यवस्थापन",
    "Delete listing": "नोंद हटवा",
    "Nearest market": "जवळची बाजारपेठ",
    "Variety preferred": "पसंतीची जात",
    "leave blank for any": "कोणतीही चालेल — रिकामे ठेवा",
    "e.g. Thompson Seedless, Bhagwa": "उदा. थॉमसन सीडलेस, भगवा",
    "e.g. Lasalgaon": "उदा. लासलगाव",
    "e.g. Cold store, MIDC Satpur, Nashik": "उदा. शीतगृह, MIDC सातपूर, नाशिक",
    "Used for the price band.": "दर पट्ट्यासाठी वापरले जाते.",
    "Pruning date, irrigation, spray schedule, packing available, transport…": "छाटणीची तारीख, पाणी, फवारणी वेळापत्रक, पॅकिंग उपलब्ध, वाहतूक…",
    "My requirements": "माझ्या मागण्या",
    "Requirement details": "मागणीचा तपशील",
    "Requirements that match one of your lots are shown first.": "तुमच्या लॉटशी जुळणाऱ्या मागण्या आधी दाखवल्या आहेत.",
    "Only ones I can fulfil": "फक्त मी पूर्ण करू शकेन अशा",
    "You can fulfil this": "ही तुम्ही पूर्ण करू शकता",
    "Offer one of my lots": "माझा एक लॉट देऊ करा",
    "Which lot?": "कोणता लॉट?",
    "For requirement": "या मागणीसाठी",
    "Linked requirement": "जोडलेली मागणी",
    "Link to one of my requirements": "माझ्या एका मागणीशी जोडा",
    "Open requirement": "मागणी उघडा",
    "Open &amp; see matching lots": "उघडा व जुळणारे लॉट पहा",
    "Close, but not matching every condition": "जवळपास, पण सर्व अटी पूर्ण करत नाहीत",
    "No farmer has offered against this requirement yet.": "या मागणीसाठी अद्याप कोणत्याही शेतकऱ्याने देऊ केलेले नाही.",
    "You have not posted any requirement yet.": "तुम्ही अद्याप कोणतीही मागणी प्रसिद्ध केलेली नाही.",
    "Nothing matches yet. Post a requirement, or": "अद्याप काहीही जुळत नाही. मागणी प्रसिद्ध करा, किंवा",
    "Notes for farmers": "शेतकऱ्यांसाठी सूचना",
    "Packing, payment terms, inspection, transport arrangement…": "पॅकिंग, पैसे देण्याच्या अटी, तपासणी, वाहतूक व्यवस्था…",
    "Organic produce only": "फक्त सेंद्रिय माल",
    "Verified quality certificate mandatory": "पडताळलेले गुणवत्ता प्रमाणपत्र आवश्यक",
    "Price range": "दर मर्यादा",
    "Price range (₹ per quintal)": "दर मर्यादा (₹ प्रति क्विंटल)",
    "Leave blank to invite open offers.": "खुल्या देकारांसाठी रिकामे ठेवा.",
    "Budget": "अंदाजपत्रक",
    "Needed by": "यापर्यंत हवे",
    "Delivery": "पोहोच",
    "Delivery location": "पोहोचण्याचे ठिकाण",
    "Delivery to": "येथे पोहोच",
    "District preferred": "पसंतीचा जिल्हा",
    "Region": "विभाग",
    "Post requirements, receive offers": "मागण्या प्रसिद्ध करा, देकार मिळवा",
    "Matching lots appear on your requirement page, ranked by quality.": "जुळणारे लॉट तुमच्या मागणी पानावर गुणवत्तेनुसार क्रमाने दिसतात.",
    "Farmers can send you offers against the requirement.": "शेतकरी या मागणीसाठी तुम्हाला देकार पाठवू शकतात.",
    "The requirement closes automatically once the full quantity is met.": "पूर्ण प्रमाण मिळाल्यावर मागणी आपोआप बंद होते.",
    "Every farmer with that crop listed is notified.": "ते पीक नोंदवलेल्या प्रत्येक शेतकऱ्याला कळवले जाते.",
    "Setting a": "एक",
    "realistic price ceiling": "वास्तववादी कमाल दर",
    "Deal accepted.": "व्यवहार स्वीकारला.",
    "Accepting reserves the lot and shares contact details with the other side.": "स्वीकारल्यास लॉट राखून ठेवला जातो व संपर्क तपशील समोरच्या बाजूस दिला जातो.",
    "Arrange delivery and payment directly, then mark it complete.": "पोहोच व पैसे थेट ठरवा, नंतर पूर्ण म्हणून खूण करा.",
    "Cancel deal": "व्यवहार रद्द करा",
    "Withdraw this request": "ही विनंती मागे घ्या",
    "Open the request thread": "विनंतीचा धागा उघडा",
    "Open the full listing": "संपूर्ण नोंद उघडा",
    "Opening message": "सुरुवातीचा संदेश",
    "Response note": "उत्तराची नोंद",
    "Optional note — delivery date, packing, payment terms…": "ऐच्छिक नोंद — पोहोचण्याची तारीख, पॅकिंग, पैशाच्या अटी…",
    "Message to the buyer (packing, transport, when you can deliver)": "खरेदीदाराला संदेश (पॅकिंग, वाहतूक, कधी पोहोच देऊ शकता)",
    "When you need delivery, packing requirement, payment terms…": "पोहोच कधी हवी, पॅकिंगची गरज, पैशाच्या अटी…",
    "Your price (₹/q)": "तुमचा दर (₹/क्विं)",
    "This thread is closed for new messages.": "या धाग्यावर नवीन संदेश पाठवता येणार नाहीत.",
    "No messages yet — say hello and agree the details.": "अद्याप संदेश नाहीत — नमस्कार करा व तपशील ठरवा.",
    "No buyer has requested this lot yet.": "या लॉटसाठी अद्याप कोणत्याही खरेदीदाराने विनंती केलेली नाही.",
    "No offers pending. Post a requirement and farmers will come to you.": "प्रलंबित देकार नाहीत. मागणी प्रसिद्ध करा, शेतकरी तुमच्याकडे येतील.",
    "No pending requests right now.": "सध्या प्रलंबित विनंत्या नाहीत.",
    "The farmer can accept, decline or negotiate. Nothing is charged here.": "शेतकरी स्वीकारू, नाकारू किंवा घासाघीस करू शकतो. येथे कोणतेही शुल्क नाही.",
    "Phone and email are revealed once the deal is accepted.": "व्यवहार स्वीकारल्यावरच फोन व ईमेल दिसतो.",
    "Contact details are shared once a request is accepted.": "विनंती स्वीकारल्यावर संपर्क तपशील दिला जातो.",
    "wants": "यांना हवे",
    "offers": "देऊ करतात",
    "directly.": "थेट.",
    "Certificate": "प्रमाणपत्र",
    "certificate": "प्रमाणपत्र",
    "Certificate file": "प्रमाणपत्र फाईल",
    "Certificate number": "प्रमाणपत्र क्रमांक",
    "Certificate required": "प्रमाणपत्र आवश्यक",
    "Certificate type": "प्रमाणपत्राचा प्रकार",
    "Certificate verification": "प्रमाणपत्र पडताळणी",
    "certificate verified": "प्रमाणपत्र पडताळले",
    "Upload quality certificate": "गुणवत्ता प्रमाणपत्र चढवा",
    "Upload &amp; verify": "चढवा व पडताळा",
    "Upload a better copy": "अधिक स्पष्ट प्रत चढवा",
    "Remove this certificate": "हे प्रमाणपत्र काढा",
    "Uploaded": "चढवले",
    "Uploaded document": "चढवलेले कागदपत्र",
    "Verification checks": "पडताळणी तपासण्या",
    "Verified at": "पडताळणी वेळ",
    "Valid until": "वैध मुदत",
    "Issue date": "दिल्याची तारीख",
    "Issuing authority": "देणारी यंत्रणा",
    "Holder on document": "कागदपत्रावरील धारक",
    "Extracted fields": "काढलेली माहिती",
    "Raw OCR output": "मूळ OCR मजकूर",
    "Open PDF": "PDF उघडा",
    "View report": "अहवाल पहा",
    "Report": "अहवाल",
    "Full report": "संपूर्ण अहवाल",
    "confidence": "विश्वास",
    "No check details were recorded for this document.": "या कागदपत्रासाठी तपासणीचा तपशील नोंदवलेला नाही.",
    "Buyers cannot send a request for this lot until one is verified.": "पडताळणी होईपर्यंत खरेदीदार या लॉटसाठी विनंती पाठवू शकत नाहीत.",
    "Send a request to see the full verification report": "संपूर्ण पडताळणी अहवाल पाहण्यासाठी विनंती पाठवा",
    "Not required": "आवश्यक नाही",
    "What the OCMR check does": "OCMR तपासणी काय करते",
    "Automatic rejection happens when": "आपोआप नाकारले जाते जेव्हा",
    "the document cannot be read at all;": "कागदपत्र वाचताच येत नाही;",
    "the certificate has already expired;": "प्रमाणपत्राची मुदत संपली आहे;",
    "it refers to a different crop than this listing.": "ते या नोंदीपेक्षा वेगळ्या पिकाचे आहे.",
    "Prepare": "तयारी",
    "Read": "वाचन",
    "Extract": "माहिती काढणे",
    "Mark": "खूण",
    "Tamper check": "फेरफार तपासणी",
    "Decide": "निर्णय",
    "Type": "प्रकार",
    "whole page": "संपूर्ण पान",
    "JPG, PNG or PDF, up to 8 MB. Scan or photograph the": "JPG, PNG किंवा PDF, ८ MB पर्यंत. स्कॅन करा किंवा फोटो काढा —",
    "— denoise, deskew and binarise the scan.": "— स्कॅनमधील गोंगाट काढा, तिरकसपणा सरळ करा व द्विमान करा.",
    "— Tesseract OCR extracts the text with a confidence score.": "— Tesseract OCR विश्वास गुणासह मजकूर काढते.",
    "— certificate number, issuing authority, issue and expiry dates, holder, crop and grade.": "— प्रमाणपत्र क्रमांक, देणारी यंत्रणा, दिल्याची व मुदतीची तारीख, धारक, पीक व प्रत.",
    "— any QR code is decoded and matched against the printed number.": "— QR सांकेतिक चिन्ह वाचून छापील क्रमांकाशी जुळवले जाते.",
    "— error-level analysis flags digitally edited documents.": "— त्रुटी-स्तर विश्लेषण संगणकावर बदललेली कागदपत्रे दाखवते.",
    "— ten weighted checks produce a confidence score and a verdict.": "— दहा भारित तपासण्या विश्वास गुण व निर्णय देतात.",
    "— detect automatically —": "— आपोआप ओळखा —",
    "Image preparation: denoise, deskew, adaptive binarisation.": "प्रतिमा तयारी: गोंगाट काढणे, तिरकसपणा सरळ करणे, अनुकूल द्विमान.",
    "Tesseract OCR with per-word confidence.": "प्रत्येक शब्दाच्या विश्वासासह Tesseract OCR.",
    "Field extraction by regular expression — number, issuer, dates, holder, crop, grade.": "नियमित अभिव्यक्तीने माहिती काढणे — क्रमांक, देणारा, तारखा, धारक, पीक, प्रत.",
    "QR / barcode detection and cross-check against the printed number.": "QR / बारकोड ओळख व छापील क्रमांकाशी पडताळणी.",
    "Error Level Analysis to flag digitally edited documents.": "संगणकावर बदललेली कागदपत्रे दाखवण्यासाठी त्रुटी-स्तर विश्लेषण.",
    "Latest modal price": "ताजा मोडल दर",
    "Period average": "कालावधीतील सरासरी",
    "Period range": "कालावधीतील मर्यादा",
    "Change over the period": "कालावधीतील बदल",
    "Price momentum": "दर गती",
    "Supply pressure": "पुरवठा दाब",
    "Season": "हंगाम",
    "Marketplace pull": "बाजारपेठ ओढ",
    "demand index": "मागणी निर्देशांक",
    "Demand &amp; market": "मागणी व बाजार",
    "Demand forecast for your region": "तुमच्या भागासाठी मागणी अंदाज",
    "Direction": "दिशा",
    "Trend": "कल",
    "Price now": "आजचा दर",
    "Projected": "अंदाजित",
    "Range": "मर्यादा",
    "Week": "आठवडा",
    "Weekly mandi arrivals (supply)": "साप्ताहिक बाजार आवक (पुरवठा)",
    "Your district": "तुमचा जिल्हा",
    "District-level price suggestion": "जिल्हा पातळीवर दर सूचना",
    "No market data is available for this region yet. Run": "या भागासाठी अद्याप बाजार माहिती उपलब्ध नाही. चालवा",
    "— last 30 days against the 90 days before.": "— मागील ३० दिवस व त्याआधीचे ९० दिवस यांची तुलना.",
    "— falling mandi arrivals with firm prices means tight supply.": "— दर टिकून असताना आवक घटणे म्हणजे पुरवठा कमी.",
    "— the crop's own lean/glut calendar.": "— त्या पिकाचे स्वतःचे टंचाई/अतिरेक वेळापत्रक.",
    "— open buyer requirements against available listings on AgriVision itself.": "— AgriVision वरील खुल्या मागण्या व उपलब्ध नोंदी यांचे प्रमाण.",
    "— how much of the produce falls inside the healthy hue range for that crop, and how vivid it is.": "— त्या पिकाच्या निरोगी रंगछटेत किती माल बसतो आणि रंग किती ठळक आहे.",
    "— circular standard deviation of hue; a consistent lot grades higher because buyers pay for consistency.": "— रंगछटेचे वर्तुळाकार प्रमाण विचलन; एकसारखा लॉट जास्त प्रत मिळवतो कारण खरेदीदार एकसारखेपणाला जास्त दर देतात.",
    "— dark-spot and bruise ratio found by adaptive thresholding inside the produce mask.": "— मालाच्या भागात अनुकूल उंबरठ्याने सापडलेले काळे डाग व मार यांचे प्रमाण.",
    "— contour analysis of individual units and how consistent they are.": "— प्रत्येक नगाचे बाह्यरेखा विश्लेषण व त्यांचा एकसारखेपणा.",
    "This lot has not been graded automatically.": "या लॉटची आपोआप प्रतवारी झालेली नाही.",
    "Email": "ईमेल",
    "Email and mobile are your login IDs and cannot be changed here.": "ईमेल व मोबाईल हेच तुमचे लॉगिन आहेत; ते येथे बदलता येत नाहीत.",
    "Company / firm": "कंपनी / पेढी",
    "Taluka": "तालुका",
    "Drives your regional price and demand insights.": "यावरून तुमच्या भागाचे दर व मागणी ठरते.",
    "Profile &amp; settings": "प्रोफाइल व सेटिंग्ज",
    "Already have an account?": "आधीच खाते आहे?",
    "Demo accounts": "नमुना खाती",
    "Farmer —": "शेतकरी —",
    "Buyer —": "खरेदीदार —",
    "Get started": "सुरुवात करा",
    "Registration is free for both sides.": "दोन्ही बाजूंसाठी नोंदणी मोफत आहे.",
    "Access denied": "प्रवेश नाकारला",
    "Page not found": "पान सापडले नाही",
    "Back to home": "मुख्य पानावर परत",
    "Back to the lot": "लॉटकडे परत",
    "The page you were looking for does not exist, or has been removed.": "तुम्ही शोधत असलेले पान अस्तित्वात नाही किंवा काढून टाकले आहे.",
    "This page belongs to the other side of the platform, or to another user's account.": "हे पान मंचाच्या दुसऱ्या बाजूचे किंवा दुसऱ्या वापरकर्त्याच्या खात्याचे आहे.",
    "Mark all read": "सर्व वाचले म्हणून खूण करा",
    "What happens when you submit": "तुम्ही पाठवल्यावर काय होते",
    "What happens next": "पुढे काय होते",
    "Your photos are saved and analysed by the computer-vision grader.": "तुमचे फोटो जतन होऊन संगणक-दृष्टी प्रतवारीने तपासले जातात.",
    "The price band is recalculated using that grade.": "त्या प्रतीनुसार दर पट्टा पुन्हा मोजला जातो.",
    "If the crop needs a certificate, you will be asked to upload it next.": "पिकाला प्रमाणपत्र लागत असल्यास पुढे ते चढवण्यास सांगितले जाईल.",
    "The crop type cannot be changed — create a new listing instead.": "पिकाचा प्रकार बदलता येत नाही — त्याऐवजी नवीन नोंद करा.",
    "Up to 5 photos, JPG or PNG, max 8 MB each. Daylight, close-up, produce filling the frame.": "जास्तीत जास्त ५ फोटो, JPG किंवा PNG, प्रत्येकी ८ MB पर्यंत. दिवसाउजेडी, जवळून, चौकट मालाने भरलेली.",
    "Adds a 15% premium to the suggested price.": "सुचवलेल्या दरात १५% वाढ करते.",
    "— select the crop —": "— पीक निवडा —",
    "— not linked —": "— जोडलेले नाही —",
    "Grading has not produced a result for this lot. Upload clearer photos and run the grader again.": "या लॉटसाठी प्रतवारीचा निकाल मिळाला नाही. अधिक स्पष्ट फोटो चढवा व प्रतवारी पुन्हा चालवा.",
    "No buyer requirement matches your current lots. Keep your listings updated — matches appear here automatically.": "तुमच्या सध्याच्या लॉटशी कोणतीही मागणी जुळत नाही. नोंदी अद्ययावत ठेवा — जुळणी येथे आपोआप दिसेल.",
    "Buying smart on AgriVision": "AgriVision वर हुशारीने खरेदी",
    "Every lot carries an AI grade — filter on it instead of travelling to inspect.": "प्रत्येक लॉटला AI प्रत असते — पाहायला जाण्याऐवजी तीवरून गाळा.",
    "The fair-price band tells you when an asking price is above the market.": "मागितलेला दर बाजारापेक्षा जास्त आहे का हे रास्त दर पट्टा सांगतो.",
    "when you need export-grade paperwork.": "निर्यात दर्जाची कागदपत्रे हवी असताना.",
    "Check the demand index — it tells you whether to buy now or wait.": "मागणी निर्देशांक पहा — आता खरेदी करावी की थांबावे हे तो सांगतो.",
    "Tick": "खूण करा",
    "View": "पहा",
    "View &amp; request": "पहा व विनंती करा",
    "Other": "इतर",
    "For": "यासाठी",
    "from ₹": "₹ पासून",
    "No listed lot currently satisfies all the conditions of this requirement. Relaxing the grade, the price ceiling or the certificate condition would widen the pool.": "सध्या नोंदवलेला कोणताही लॉट या मागणीच्या सर्व अटी पूर्ण करत नाही. प्रत, कमाल दर किंवा प्रमाणपत्राची अट थोडी सैल केल्यास अधिक पर्याय मिळतील.",
    "AgriVision is a direct farmer-to-buyer marketplace. Four AI modules sit behind the screens and do the work an agent or commission agent would otherwise do — grading the produce, fixing a fair price, judging demand and checking the paperwork.": "AgriVision ही शेतकरी ते खरेदीदार अशी थेट बाजारपेठ आहे. पडद्यामागे चार AI घटक तेच काम करतात जे एरवी दलाल किंवा आडत्या करतो — मालाची प्रतवारी, रास्त दर ठरवणे, मागणीचा अंदाज आणि कागदपत्रांची तपासणी.",
    "When a farmer uploads photos of a lot, OpenCV separates the produce from the background and measures four independent attributes:": "शेतकऱ्याने लॉटचे फोटो चढवल्यावर OpenCV माल पार्श्वभूमीपासून वेगळा करते आणि चार स्वतंत्र गुणधर्म मोजते:",
    "These are fused into a 0–100 score and a Grade A / B / C verdict. A blurred or badly lit photo caps the score instead of inflating it, and the farmer is told to re-shoot.": "हे एकत्र करून ०–१०० गुण व प्रत A / B / C ठरवली जाते. अस्पष्ट किंवा कमी प्रकाशातील फोटोमुळे गुण वाढत नाहीत तर मर्यादित होतात, आणि शेतकऱ्याला पुन्हा फोटो काढण्यास सांगितले जाते.",
    "The suggested price starts from the median modal price of the last 45 days in the farmer's own district and is then adjusted by four multiplicative factors:": "सुचवलेला दर शेतकऱ्याच्याच जिल्ह्यातील मागील ४५ दिवसांच्या मध्यक मोडल दरापासून सुरू होतो आणि नंतर चार गुणक घटकांनी समायोजित केला जातो:",
    "Every factor is shown to the farmer with its reason, so the number is never a black box. The band width comes from that crop's historical volatility — wide for tomato, narrow for wheat.": "प्रत्येक घटक त्याच्या कारणासह शेतकऱ्याला दाखवला जातो, त्यामुळे हा आकडा कधीही गूढ राहत नाही. पट्ट्याची रुंदी त्या पिकाच्या पूर्वीच्या दरचढउतारावरून ठरते — टोमॅटोसाठी रुंद, गव्हासाठी अरुंद.",
    "A least-squares trend over the weekly means, modulated by seasonality, gives a six-week price forecast with a widening confidence band.": "साप्ताहिक सरासरीवरील अल्प-वर्ग कल, हंगामानुसार समायोजित करून, रुंदावत जाणाऱ्या विश्वास पट्ट्यासह सहा आठवड्यांचा दर अंदाज देतो.",
    "OCMR — Optical Certificate &amp; Mark Recognition — is the six-stage pipeline that reads a quality certificate and decides whether to trust it:": "OCMR — ऑप्टिकल सर्टिफिकेट अँड मार्क रेकग्निशन — ही सहा टप्प्यांची प्रक्रिया गुणवत्ता प्रमाणपत्र वाचते आणि त्यावर विश्वास ठेवायचा की नाही हे ठरवते:",
    "Expired certificates, wrong-crop certificates and unreadable scans are rejected outright; borderline cases are queued for manual review rather than silently passed.": "मुदत संपलेली, चुकीच्या पिकाची किंवा न वाचता येणारी प्रमाणपत्रे थेट नाकारली जातात; संशयास्पद प्रकरणे गुपचूप मंजूर न करता माणसाच्या तपासणीसाठी ठेवली जातात.",
    "A farmer who does not know the going rate is at the mercy of whoever is standing in the field. Transparent grading and a published fair-price band shift that balance — and a buyer gets a quality signal he can filter on before he ever travels to see the lot.": "चालू दर माहीत नसलेला शेतकरी शेतात उभ्या असलेल्या माणसाच्या मर्जीवर अवलंबून राहतो. पारदर्शक प्रतवारी आणि जाहीर केलेला रास्त दर पट्टा हे संतुलन बदलतात — आणि खरेदीदाराला लॉट पाहायला जाण्यापूर्वीच गाळण्यासाठी गुणवत्तेचा आधार मिळतो.",
    "fuses price momentum (38%), supply pressure from mandi arrivals (24%), the crop's seasonal calendar (18%) and AgriVision's own requirement-vs-listing balance (20%). 50 is a neutral market; above 70 is a seller's market.": "दर गती (३८%), बाजार आवकेतून येणारा पुरवठा दाब (२४%), पिकाचे हंगामी वेळापत्रक (१८%) आणि AgriVision वरील मागणी-विरुद्ध-नोंदी यांचे प्रमाण (२०%) एकत्र करतो. ५० म्हणजे तटस्थ बाजार; ७० च्या वर विक्रेत्याचा बाजार.",
    "Each bar is one week of arrivals — the quantity reaching the market. Falling arrivals with firm prices mean supply is tightening — usually a good time for a farmer to sell.": "प्रत्येक स्तंभ म्हणजे एका आठवड्याची आवक — बाजारात पोहोचणारे प्रमाण. दर टिकून असताना आवक घटणे म्हणजे पुरवठा कमी होत आहे — शेतकऱ्यासाठी विकण्याची साधारणपणे चांगली वेळ.",
    "Based on": "आधार —",
    "Buying request": "खरेदी विनंती",
    "Farmer offer": "शेतकऱ्याचा देकार",
    "Started by the": "सुरू करणारा —",
    "Listed asking price is": "नोंदवलेला मागितलेला दर आहे",
    "Accept this": "हे स्वीकारा",
    "Waiting for": "प्रतीक्षेत —",
    "to respond": "यांच्या उत्तराची",
    "This trade is complete": "हा व्यवहार पूर्ण झाला आहे",
    "quintal at": "क्विंटल या दराने",
    "This request was": "ही विनंती",
    "or better": "किंवा वरची",
    "Register as": "म्हणून नोंदणी करा",
    "Harvested": "काढणी",
    "On AgriVision since": "AgriVision वर तारखेपासून",
    "acre farm": "एकर शेती",
    "lots": "लॉट",
    "You have a pending request on this lot for": "या लॉटवर तुमची प्रलंबित विनंती आहे —",
    "This lot is": "हा लॉट",
    "and cannot be requested": "असल्याने विनंती करता येणार नाही",
    "Scope": "व्याप्ती",
    "Full": "संपूर्ण",
    "report": "अहवाल",
    "Offers received": "मिळालेले देकार",
    "q at": "क्विं या दराने",
    "Total": "एकूण",
    "Lots that meet every condition": "सर्व अटी पूर्ण करणारे लॉट",
    "market": "बाजार",
    "Your ceiling of": "तुमची कमाल मर्यादा",
    "is below the current market price of": "ही सध्याच्या बाजारभावापेक्षा कमी आहे —",
    "up to": "पर्यंत",
    "open": "खुले",
    "OCMR verification": "OCMR पडताळणी",
    "weight": "भार",
    "views": "पाहण्या",
    "Mark as": "अशी खूण करा —",
    "requires a verified quality certificate": "साठी पडताळलेले गुणवत्ता प्रमाणपत्र आवश्यक आहे",
    "No certificate uploaded yet": "अद्याप प्रमाणपत्र चढवलेले नाही",
    "No certificate needed for": "यासाठी प्रमाणपत्र आवश्यक नाही —",
    "Namaste": "नमस्कार",
    "Negotiable": "वाटाघाटीयोग्य",
    "projected change over": "या कालावधीतील अंदाजित बदल —",
    "weeks": "आठवडे",
    "Demand ranking for": "यासाठी मागणी क्रमवारी —",
    "A listing must keep at least one photo.": "नोंदीसाठी किमान एक फोटो आवश्यक आहे.",
    "All notifications marked as read.": "सर्व सूचना वाचल्या म्हणून नोंदवल्या.",
    "Buying request sent to the farmer.": "खरेदी विनंती शेतकऱ्याला पाठवली.",
    "Certificate removed.": "प्रमाणपत्र काढले.",
    "Choose the certificate file to upload.": "चढवण्यासाठी प्रमाणपत्र फाईल निवडा.",
    "Deal marked as completed.": "व्यवहार पूर्ण म्हणून नोंदवला.",
    "Enter a quantity between 1 and {max:g} quintal.": "१ ते {max:g} क्विंटलदरम्यान प्रमाण नोंदवा.",
    "Listing created. AI grade: {grade} ({score:.0f}/100).": "नोंद तयार झाली. AI प्रत: {grade} ({score:.0f}/१००).",
    "Listing deleted.": "नोंद हटवली.",
    "Listing marked as {status}.": "नोंद {status} म्हणून नोंदवली.",
    "Listing updated.": "नोंद अद्ययावत केली.",
    "Logged in as {name}.": "{name} म्हणून लॉगिन झाले.",
    "None of the photos could be saved. Please try again with JPG or PNG files.": "एकही फोटो जतन करता आला नाही. कृपया JPG किंवा PNG फाईलसह पुन्हा प्रयत्न करा.",
    "Only an accepted deal can be marked complete.": "फक्त स्वीकारलेला व्यवहारच पूर्ण म्हणून नोंदवता येतो.",
    "Only {left:g} quintal is left in this lot. Reject this request or ask the buyer to revise the quantity.": "या लॉटमध्ये फक्त {left:g} क्विंटल शिल्लक आहे. ही विनंती नाकारा किंवा खरेदीदाराला प्रमाण बदलण्यास सांगा.",
    "Password updated.": "पासवर्ड बदलला.",
    "Photo removed and the lot re-graded.": "फोटो काढला व लॉटची पुन्हा प्रतवारी झाली.",
    "Please correct the highlighted fields.": "कृपया दर्शवलेली माहिती दुरुस्त करा.",
    "Profile updated.": "प्रोफाइल अद्ययावत केले.",
    "Re-analysed: grade {grade} ({score:.0f}/100).": "पुन्हा तपासले: प्रत {grade} ({score:.0f}/१००).",
    "Request accepted. The lot is now reserved — use the chat to arrange delivery.": "विनंती स्वीकारली. लॉट आता राखून ठेवला आहे — पोहोच ठरवण्यासाठी संवाद वापरा.",
    "Request declined.": "विनंती नाकारली.",
    "Request withdrawn.": "विनंती मागे घेतली.",
    "Requirement closed.": "मागणी बंद केली.",
    "Requirement reopened.": "मागणी पुन्हा उघडली.",
    "Requirement deleted.": "मागणी हटवली.",
    "Requirement posted. Matching farmers have been notified.": "मागणी प्रसिद्ध केली. जुळणाऱ्या शेतकऱ्यांना कळवले आहे.",
    "Requirement updated.": "मागणी अद्ययावत केली.",
    "That notification does not belong to your account.": "ती सूचना तुमच्या खात्याची नाही.",
    "That requirement is already closed.": "ती मागणी आधीच बंद झाली आहे.",
    "The new passwords do not match.": "नवीन पासवर्ड जुळत नाहीत.",
    "This listing has no photos to analyse.": "या नोंदीसाठी तपासण्यासारखे फोटो नाहीत.",
    "This lot is no longer available.": "हा लॉट आता उपलब्ध नाही.",
    "This lot needs a verified quality certificate before it can be traded.": "व्यवहारापूर्वी या लॉटसाठी पडताळलेले गुणवत्ता प्रमाणपत्र आवश्यक आहे.",
    "This request can no longer be withdrawn.": "ही विनंती आता मागे घेता येणार नाही.",
    "This request has already been answered.": "या विनंतीला आधीच उत्तर दिले आहे.",
    "Unknown account type.": "अनोळखी खाते प्रकार.",
    "Upload up to 5 photos, JPG or PNG.": "जास्तीत जास्त ५ फोटो चढवा, JPG किंवा PNG.",
    "Write a message before sending.": "पाठवण्यापूर्वी संदेश लिहा.",
    "You already have a pending request on this lot.": "या लॉटवर तुमची आधीच प्रलंबित विनंती आहे.",
    "You have already offered this lot against that requirement.": "तुम्ही हा लॉट त्या मागणीसाठी आधीच देऊ केला आहे.",
    "You have been logged out.": "तुम्ही लॉगआउट झाला आहात.",
    "Your current password is incorrect.": "तुमचा सध्याचा पासवर्ड चुकीचा आहे.",
    "Your offer has been sent to the buyer.": "तुमचा देकार खरेदीदाराला पाठवला.",
    "closed": "बंद",
    "verified": "पडताळले",
    "not_required": "आवश्यक नाही",
    "request": "विनंती",
    "offer": "देकार",
    "Listed asking price is {price} per quintal.": "नोंदवलेला मागितलेला दर {price} प्रति क्विंटल आहे.",
    "This offer is {amount} per quintal below the asking price ({pct}% less).": "हा देकार मागितलेल्या दरापेक्षा {amount} प्रति क्विंटल कमी आहे ({pct}% कमी).",
    "This offer is {amount} per quintal above the asking price.": "हा देकार मागितलेल्या दरापेक्षा {amount} प्रति क्विंटल जास्त आहे.",
    "The offer matches the asking price exactly.": "देकार मागितलेल्या दराशी अगदी जुळतो.",
    "Buyer dashboard": "खरेदीदार डॅशबोर्ड",
    "Farmer dashboard": "शेतकरी डॅशबोर्ड",
    "Buyer requirements": "खरेदीदारांच्या मागण्या",
    "Compare lots": "लॉटची तुलना",
    "Create an account": "खाते तयार करा",
    "Profile": "प्रोफाइल",
    "Verification report": "पडताळणी अहवाल",
    "Farmer to buyer, directly": "शेतकऱ्यांकडून थेट खरेदीदारांपर्यंत",
    "More buyers than sellers for": "विक्रेत्यांपेक्षा जास्त खरेदीदार —",
    "farmers have the upper hand.": "शेतकऱ्यांचे पारडे जड आहे.",
    "More listings than requirements — buyers can negotiate harder.": "मागण्यांपेक्षा नोंदी जास्त — खरेदीदार अधिक घासाघीस करू शकतात.",
    "Supply and demand are balanced on the platform.": "मंचावर पुरवठा व मागणी संतुलित आहे.",
    "wants {qty:g} quintal of {crop}": "यांना {crop} चे {qty:g} क्विंटल हवे",
    "at {price} per quintal · total {total}": "{price} प्रति क्विंटल दराने · एकूण {total}",
    "matches your {crop} lot ({qty:g} quintal, grade {grade})": "तुमच्या {crop} लॉटशी जुळते ({qty:g} क्विंटल, प्रत {grade})",
}


# ======================================================================
# HINDI
# ======================================================================
HI = {
    # --- navigation and chrome ---------------------------------------
    "Dashboard": "डैशबोर्ड",
    "My Crops": "मेरी फसलें",
    "Buyer Requirements": "खरीदारों की मांग",
    "Marketplace": "बाज़ार",
    "My Requirements": "मेरी मांगें",
    "Deals": "सौदे",
    "Market Insights": "बाज़ार जानकारी",
    "How it works": "यह कैसे काम करता है",
    "Log in": "लॉग इन",
    "Log out": "लॉग आउट",
    "Register free": "मुफ़्त पंजीकरण",
    "Profile & settings": "प्रोफ़ाइल और सेटिंग्स",
    "Notifications": "सूचनाएं",
    "Language": "भाषा",
    "Home": "मुख्य पृष्ठ",
    "Platform": "प्लेटफ़ॉर्म",
    "AI modules": "एआई मॉड्यूल",
    "Farmer": "किसान",
    "Buyer": "खरीदार",
    "farmer": "किसान",
    "buyer": "खरीदार",

    # --- common words -------------------------------------------------
    "Crop": "फसल",
    "Crops": "फसलें",
    "Variety": "किस्म",
    "Quantity": "मात्रा",
    "Price": "कीमत",
    "Grade": "ग्रेड",
    "Quality": "गुणवत्ता",
    "Location": "स्थान",
    "District": "जिला",
    "Taluka / Tehsil": "तहसील",
    "State": "राज्य",
    "PIN code": "पिन कोड",
    "Market": "मंडी",
    "quintal": "क्विंटल",
    "Status": "स्थिति",
    "Available": "उपलब्ध",
    "available": "उपलब्ध",
    "reserved": "आरक्षित",
    "sold": "बिक गया",
    "withdrawn": "वापस लिया",
    "Organic": "जैविक",
    "Certified": "प्रमाणित",
    "Certificate pending": "प्रमाणपत्र लंबित",
    "Certificate rejected": "प्रमाणपत्र अस्वीकृत",
    "No certificate needed": "प्रमाणपत्र आवश्यक नहीं",
    "Save changes": "बदलाव सहेजें",
    "Cancel": "रद्द करें",
    "Delete": "हटाएं",
    "Edit": "संपादित करें",
    "View all": "सभी देखें",
    "See all": "सभी देखें",
    "Manage all": "सभी प्रबंधित करें",
    "Apply filters": "फ़िल्टर लगाएं",
    "Clear all": "सब साफ़ करें",
    "Filters": "फ़िल्टर",
    "Sort by": "क्रम",
    "Newest first": "नवीनतम पहले",
    "Back to marketplace": "बाज़ार पर वापस",
    "My crops": "मेरी फसलें",
    "Send": "भेजें",
    "Compare": "तुलना करें",
    "just now": "अभी",
    "Not graded": "ग्रेड नहीं",
    "Nothing here": "यहां कुछ नहीं",
    "All crops": "सभी फसलें",
    "Any grade": "कोई भी ग्रेड",
    "any": "कोई भी",
    "no limit": "कोई सीमा नहीं",
    "All": "सभी",
    "Open": "खुला",
    "Closed": "बंद",

    # --- crops ---------------------------------------------------------
    "Grapes": "अंगूर",
    "Pomegranate": "अनार",
    "Mango": "आम",
    "Banana": "केला",
    "Tomato": "टमाटर",
    "Onion": "प्याज",
    "Potato": "आलू",
    "Wheat": "गेहूं",
    "Rice": "चावल",
    "Maize": "मक्का",
    "Soybean": "सोयाबीन",
    "Cotton": "कपास",
    "Sugarcane": "गन्ना",
    "Chilli": "मिर्च",

    # --- home page ------------------------------------------------------
    "Sell your harvest at the price it deserves.":
        "अपनी उपज को उसका सही दाम दिलाएं।",
    "AgriVision connects farmers directly with buyers — no middlemen. Upload a "
    "photo of your crop and our AI grades its quality, suggests a fair price from "
    "live regional trends, predicts demand, and verifies your quality certificates.":
        "एग्रीविज़न किसानों को सीधे खरीदारों से जोड़ता है — बिचौलियों के बिना। अपनी फसल की "
        "फोटो अपलोड करें; हमारा एआई गुणवत्ता का ग्रेड तय करता है, स्थानीय मंडी भाव से सही दाम "
        "बताता है, मांग का अनुमान लगाता है और आपके प्रमाणपत्र जांचता है।",
    "I am a Farmer": "मैं किसान हूं",
    "I am a Buyer": "मैं खरीदार हूं",
    "Go to my dashboard": "मेरे डैशबोर्ड पर जाएं",
    "Farmers": "किसान",
    "Buyers": "खरीदार",
    "Live listings": "चालू सूचियां",
    "Open requirements": "खुली मांगें",
    "Deals struck": "हुए सौदे",
    "Quintal available": "उपलब्ध क्विंटल",
    "How AgriVision works": "एग्रीविज़न कैसे काम करता है",
    "Photograph the lot": "माल की फोटो लें",
    "The farmer uploads photos, quantity and location. No paperwork, no agent visit.":
        "किसान फोटो, मात्रा और स्थान दर्ज करता है। कोई कागज़ी कार्रवाई नहीं, कोई एजेंट नहीं।",
    "AI grades and prices it": "एआई ग्रेड और दाम तय करता है",
    "Computer vision scores colour, uniformity, defects and size, then a price "
    "band is computed from district mandi trends.":
        "कंप्यूटर विज़न रंग, एकरूपता, दोष और आकार जांचता है, फिर जिले के मंडी भाव से उचित दाम "
        "की सीमा निकाली जाती है।",
    "Certificates verified": "प्रमाणपत्र जांचे जाते हैं",
    "For grapes and other export crops the certificate is read by OCR and checked "
    "against the issuing authority's format and validity.":
        "अंगूर जैसी निर्यात फसलों के लिए प्रमाणपत्र ओसीआर से पढ़ा जाता है और जारी करने वाली "
        "संस्था के प्रारूप व वैधता से मिलाया जाता है।",
    "Deal directly": "सीधा सौदा करें",
    "Buyers post requirements or send buying requests. Both sides negotiate in one "
    "thread and close the trade.":
        "खरीदार मांग दर्ज करते हैं या खरीद अनुरोध भेजते हैं। दोनों पक्ष एक ही जगह बातचीत कर "
        "सौदा पूरा करते हैं।",
    "Top-graded lots on the platform": "प्लेटफ़ॉर्म पर सर्वोत्तम ग्रेड का माल",
    "Buyers are looking for": "खरीदारों को चाहिए",
    "Grade {g} or better": "ग्रेड {g} या बेहतर",

    # --- auth ------------------------------------------------------------
    "Create your free account": "अपना मुफ़्त खाता बनाएं",
    "AgriVision keeps the two sides of the market separate. Choose the side you "
    "are on — each one gets its own dashboard and tools.":
        "एग्रीविज़न में बाज़ार के दोनों पक्ष अलग रहते हैं। आप किस ओर हैं चुनें — हर एक को अपना "
        "डैशबोर्ड और साधन मिलते हैं।",
    "Register as Farmer": "किसान के रूप में पंजीकरण करें",
    "Register as Buyer": "खरीदार के रूप में पंजीकरण करें",
    "List your crops, get an AI quality grade and a fair price band, see what "
    "buyers are asking for, and sell directly.":
        "अपनी फसलें दर्ज करें, एआई से गुणवत्ता ग्रेड और उचित दाम की सीमा पाएं, खरीदारों की "
        "मांग देखें और सीधे बेचें।",
    "Post what you need, browse graded lots with verified quality, compare them "
    "side by side and buy straight from the farmer.":
        "आपको जो चाहिए वह दर्ज करें, ग्रेड किया हुआ माल देखें, उनकी तुलना करें और सीधे किसान "
        "से खरीदें।",
    "Already registered?": "पहले से पंजीकृत हैं?",
    "Log in here": "यहां लॉग इन करें",
    "Welcome back": "फिर से स्वागत है",
    "Log in to your AgriVision account": "अपने एग्रीविज़न खाते में लॉग इन करें",
    "Email or mobile number": "ईमेल या मोबाइल नंबर",
    "Password": "पासवर्ड",
    "Keep me logged in": "मुझे लॉग इन रखें",
    "New to AgriVision?": "एग्रीविज़न पर नए हैं?",
    "Create a free account": "मुफ़्त खाता बनाएं",
    "Your details": "आपकी जानकारी",
    "Full name": "पूरा नाम",
    "Mobile number": "मोबाइल नंबर",
    "Email address": "ईमेल पता",
    "Farm size (acres)": "खेत का क्षेत्रफल (एकड़)",
    "Company / firm name": "कंपनी / फर्म का नाम",
    "Type of buyer": "खरीदार का प्रकार",
    "GST number": "जीएसटी नंबर",
    "Security": "सुरक्षा",
    "Confirm password": "पासवर्ड की पुष्टि करें",
    "Create account": "खाता बनाएं",
    "Change account type": "खाते का प्रकार बदलें",
    "At least 6 characters.": "कम से कम ६ अक्षर।",
    "Your district decides which mandi prices and demand forecasts you are shown, "
    "so please fill it accurately.":
        "आपका जिला तय करता है कि आपको कौन से मंडी भाव और मांग के अनुमान दिखेंगे, इसलिए इसे "
        "सही भरें।",
    "Account details": "खाते की जानकारी",
    "Change password": "पासवर्ड बदलें",
    "Current password": "वर्तमान पासवर्ड",
    "New password": "नया पासवर्ड",
    "Confirm new password": "नए पासवर्ड की पुष्टि करें",
    "Update password": "पासवर्ड बदलें",
    "Member since": "सदस्य बने",

    # --- farmer -----------------------------------------------------------
    "List a new crop": "नई फसल दर्ज करें",
    "List a crop": "फसल दर्ज करें",
    "My crop listings": "मेरी फसल सूचियां",
    "Quintal on sale": "बिक्री के लिए क्विंटल",
    "Potential value": "संभावित रकम",
    "Pending requests": "लंबित अनुरोध",
    "Accepted deals": "स्वीकृत सौदे",
    "Listing views": "सूची देखी गई",
    "Buying requests waiting for you": "आपके लिए लंबित खरीद अनुरोध",
    "My recent listings": "मेरी हाल की सूचियां",
    "Buyer requirements that match your crops": "आपकी फसलों से मेल खाती मांगें",
    "Demand in {place}": "{place} में मांग",
    "Full market insights": "पूरी बाज़ार जानकारी",
    "Tips for a better grade": "बेहतर ग्रेड के लिए सुझाव",
    "Shoot in daylight, never under a tube-light.":
        "दिन के उजाले में फोटो लें, ट्यूबलाइट के नीचे नहीं।",
    "Fill the frame with the produce — no sky, no floor.":
        "फोटो में सिर्फ़ माल दिखे — आसमान या ज़मीन नहीं।",
    "Spread the lot out; overlapping fruit hides defects and lowers the size score.":
        "माल फैलाकर रखें; एक पर एक रखे फल दोष छिपाते हैं और आकार का अंक घटाते हैं।",
    "Upload 3–5 photos from different sides. The system uses the weakest side too.":
        "अलग-अलग तरफ़ से ३–५ फोटो अपलोड करें। प्रणाली सबसे कमज़ोर हिस्सा भी देखती है।",
    "Sort out damaged pieces before photographing — uniformity is 22% of the score.":
        "फोटो लेने से पहले खराब माल अलग करें — एकरूपता अंकों का २२% है।",
    "What are you selling?": "आप क्या बेच रहे हैं?",
    "Where is the lot?": "माल कहां है?",
    "Photos for AI grading": "एआई ग्रेडिंग के लिए फोटो",
    "Your price": "आपका दाम",
    "Expected price (₹ per quintal)": "अपेक्षित दाम (₹ प्रति क्विंटल)",
    "Harvest date": "कटाई की तारीख",
    "Organically grown": "जैविक तरीके से उगाया",
    "Nearest market / APMC": "नज़दीकी मंडी / कृषि उपज मंडी समिति",
    "Description / notes for buyers": "खरीदारों के लिए जानकारी",
    "AI price assistant": "एआई दाम सहायक",
    "Choose a crop to see the AI price suggestion.":
        "एआई का सुझाया दाम देखने के लिए फसल चुनें।",
    "AI quality report": "एआई गुणवत्ता रिपोर्ट",
    "Re-run AI grading": "एआई ग्रेडिंग दोबारा चलाएं",
    "Photos": "फोटो",
    "Quality certificates": "गुणवत्ता प्रमाणपत्र",
    "Upload certificate": "प्रमाणपत्र अपलोड करें",
    "Requests on this lot": "इस माल पर अनुरोध",
    "Pricing": "दाम",
    "Your asking price": "आपका मांगा दाम",
    "Lot value": "माल की कुल कीमत",
    "AI fair price band": "एआई उचित दाम सीमा",
    "Demand & market": "मांग और बाज़ार",
    "Lot details": "माल की जानकारी",
    "What buyers are looking for": "खरीदारों को क्या चाहिए",
    "Offer": "ऑफ़र दें",
    "Send offer": "ऑफ़र भेजें",

    # --- buyer -------------------------------------------------------------
    "Post a requirement": "मांग दर्ज करें",
    "Browse marketplace": "बाज़ार देखें",
    "Requests sent": "भेजे गए अनुरोध",
    "Offers to review": "देखने के लिए ऑफ़र",
    "Deals closed": "पूरे हुए सौदे",
    "Committed value": "तय रकम",
    "Total requirements": "कुल मांगें",
    "Farmer offers waiting for your answer": "आपके उत्तर की प्रतीक्षा में ऑफ़र",
    "Lots that match your open requirements": "आपकी मांगों से मेल खाता माल",
    "Minimum grade": "न्यूनतम ग्रेड",
    "Maximum price (₹/quintal)": "अधिकतम दाम (₹/क्विंटल)",
    "Minimum quantity (quintal)": "न्यूनतम मात्रा (क्विंटल)",
    "Organic only": "सिर्फ़ जैविक",
    "Certificate verified": "प्रमाणपत्र जांचा हुआ",
    "Send a buying request": "खरीद अनुरोध भेजें",
    "Send buying request": "खरीद अनुरोध भेजें",
    "Your offer (₹/quintal)": "आपका ऑफ़र (₹/क्विंटल)",
    "Message to the farmer": "किसान को संदेश",
    "The seller": "विक्रेता",
    "Market context": "बाज़ार की स्थिति",
    "Independent AI quality assessment": "स्वतंत्र एआई गुणवत्ता जांच",
    "Side-by-side comparison": "आमने-सामने तुलना",
    "Value score": "मूल्य अंक",
    "Best value": "सर्वोत्तम मूल्य",
    "View & request": "देखें और अनुरोध करें",
    "Certificates": "प्रमाणपत्र",

    # --- deals ---------------------------------------------------------------
    "Received": "प्राप्त",
    "Sent": "भेजे गए",
    "pending": "लंबित",
    "accepted": "स्वीकृत",
    "rejected": "अस्वीकृत",
    "cancelled": "रद्द",
    "completed": "पूर्ण",
    "Terms on the table": "तय शर्तें",
    "Price offered": "दिया गया दाम",
    "Total value": "कुल रकम",
    "Conversation": "बातचीत",
    "Write a message…": "संदेश लिखें…",
    "Your decision": "आपका निर्णय",
    "Decline": "अस्वीकार करें",
    "Mark as completed": "पूर्ण के रूप में दर्ज करें",
    "Contact details": "संपर्क जानकारी",
    "The lot": "माल",

    # --- insights --------------------------------------------------------------
    "Demand ranking for {place}": "{place} के लिए मांग क्रम",
    "Price history and 6-week forecast": "दाम का इतिहास और ६ सप्ताह का अनुमान",
    "Six-week outlook": "छह सप्ताह का अनुमान",
    "What is driving demand": "मांग किस वजह से है",
    "On AgriVision right now": "अभी एग्रीविज़न पर",
    "lots listed": "दर्ज माल",
    "open requirements": "खुली मांगें",
    "Update": "अपडेट करें",

    # --- onboarding --------------------------------------------------------------
    "Welcome to AgriVision": "एग्रीविज़न में आपका स्वागत है",
    "Skip for now": "अभी छोड़ें",
    "Start using AgriVision": "एग्रीविज़न इस्तेमाल करना शुरू करें",
    "You can open this guide again any time from the menu under your name.":
        "आप इस मार्गदर्शिका को अपने नाम के नीचे मेनू से कभी भी दोबारा खोल सकते हैं।",
    "How to use AgriVision": "एग्रीविज़न कैसे इस्तेमाल करें",
    "Quick start guide": "त्वरित मार्गदर्शिका",
    "Back to dashboard": "डैशबोर्ड पर वापस",
    "List my first crop": "मेरी पहली फसल दर्ज करें",
    "Browse the marketplace": "बाज़ार देखें",
    "Four things to know before you list your first crop. It takes a minute to read.":
        "पहली फसल दर्ज करने से पहले चार बातें जान लें। पढ़ने में एक मिनट लगेगा।",
    "Four things to know before you buy your first lot. It takes a minute to read.":
        "पहला माल खरीदने से पहले चार बातें जान लें। पढ़ने में एक मिनट लगेगा।",

    # farmer guide steps
    "Photograph your crop": "अपनी फसल की फोटो लें",
    "Spread the lot out in daylight and take 3 to 5 photos from different sides, "
    "filling the frame with the produce. The clearer the photo, the fairer the grade.":
        "दिन के उजाले में माल फैलाएं और अलग-अलग तरफ़ से ३ से ५ फोटो लें; फोटो में सिर्फ़ माल "
        "दिखे। फोटो जितनी साफ़, ग्रेड उतना सही।",
    "Let the AI grade and price it": "एआई को ग्रेड और दाम तय करने दें",
    "Colour, uniformity, blemishes and size are scored automatically into a Grade A, "
    "B or C. A fair price band is then worked out from the last 45 days of your own "
    "district's mandi rates.":
        "रंग, एकरूपता, दाग और आकार से अपने आप ग्रेड ए, बी या सी तय होता है। फिर आपके ही जिले "
        "के पिछले ४५ दिनों के मंडी भाव से उचित दाम की सीमा निकाली जाती है।",
    "Upload your certificate": "अपना प्रमाणपत्र अपलोड करें",
    "Grapes, pomegranate, mango and banana need a quality certificate before they can "
    "be sold here. Photograph the whole page and it is checked and verified in seconds.":
        "अंगूर, अनार, आम और केला बेचने के लिए गुणवत्ता प्रमाणपत्र ज़रूरी है। पूरे पन्ने की फोटो लें; "
        "कुछ ही सेकंड में वह जांचकर मंज़ूर हो जाता है।",
    "Answer buyers directly": "खरीदारों को सीधे जवाब दें",
    "Buyers send you requests, and you can offer your lot against what they have asked "
    "for. Accept, decline or negotiate — contact details are shared once you accept.":
        "खरीदार आपको अनुरोध भेजते हैं और आप उनकी मांग के लिए अपना माल दे सकते हैं। स्वीकार करें, "
        "मना करें या मोल-भाव करें — स्वीकार करने पर संपर्क जानकारी साझा होती है।",

    # buyer guide steps
    "Post what you need": "आपको जो चाहिए वह दर्ज करें",
    "Give the crop, quantity, minimum grade and your price range. Every farmer growing "
    "that crop is notified, and matching lots appear on your requirement page.":
        "फसल, मात्रा, न्यूनतम ग्रेड और दाम की सीमा दें। वह फसल उगाने वाले हर किसान को सूचना "
        "जाती है और मेल खाता माल आपकी मांग के पन्ने पर दिखता है।",
    "Filter on grade, not on guesswork": "अंदाज़े से नहीं, ग्रेड से चुनें",
    "Every lot carries an independent AI quality grade and, where it applies, a "
    "verified certificate. Filter on both so you only look at lots worth travelling for.":
        "हर माल पर स्वतंत्र एआई गुणवत्ता ग्रेड होता है और जहां लागू हो वहां जांचा हुआ प्रमाणपत्र भी। "
        "दोनों पर फ़िल्टर लगाएं ताकि सिर्फ़ देखने लायक माल सामने आए।",
    "Check the fair price band": "उचित दाम की सीमा देखें",
    "Each lot shows the fair price band for its grade and district alongside the asking "
    "price, so you can see at a glance whether there is room to negotiate.":
        "हर माल के साथ उसके ग्रेड और जिले के लिए उचित दाम की सीमा मांगे गए दाम के बगल में दिखती "
        "है, जिससे एक नज़र में पता चलता है कि मोल-भाव की गुंजाइश है या नहीं।",
    "Compare, then buy direct": "तुलना करें, फिर सीधे खरीदें",
    "Put up to four lots side by side and compare quality per rupee. Send a buying "
    "request straight to the farmer — no commission agent in between.":
        "चार माल आमने-सामने रखकर प्रति रुपया गुणवत्ता की तुलना करें। सीधे किसान को खरीद अनुरोध "
        "भेजें — बीच में कोई कमीशन एजेंट नहीं।",

    # --- footer ----------------------------------------------------------------------
    "A direct farmer-to-buyer marketplace with AI crop grading, price intelligence, "
    "demand prediction and certificate verification — built to cut out the middlemen.":
        "एआई ग्रेडिंग, दाम की जानकारी, मांग के अनुमान और प्रमाणपत्र जांच वाला सीधा किसान-से-"
        "खरीदार बाज़ार — बिचौलियों को हटाने के लिए बनाया गया।",
    "Computer-vision crop grading": "कंप्यूटर विज़न से फसल ग्रेडिंग",
    "Regional price recommendation": "क्षेत्रीय दाम सिफ़ारिश",
    "Demand index & 6-week forecast": "मांग सूचकांक और ६ सप्ताह का अनुमान",
    "OCMR certificate verification": "ओसीएमआर प्रमाणपत्र जांच",
    "Showing {n} lots": "{n} माल दिखा रहे हैं",
    "{n} lots available": "{n} माल उपलब्ध",
    "Can't find it? Post a requirement": "नहीं मिल रहा? मांग दर्ज करें",
    "{n} min ago": "{n} मिनट पहले",
    "{n} hr ago": "{n} घंटे पहले",
    "{n} days ago": "{n} दिन पहले",
    "yesterday": "कल",

    # --- demand labels and buyer types (passed to t() dynamically) ----------------
    "Strong demand": "मज़बूत मांग",
    "Firm demand": "स्थिर मांग",
    "Balanced market": "संतुलित बाज़ार",
    "Soft demand": "कमज़ोर मांग",
    "Weak demand": "बहुत कम मांग",
    "Trader": "व्यापारी",
    "Exporter": "निर्यातक",
    "Retailer / Mall": "खुदरा विक्रेता / मॉल",
    "Food Processor": "खाद्य प्रसंस्करण उद्योग",
    "FPO / Co-operative": "किसान उत्पादक कंपनी / सहकारी समिति",
    "Hotel / Restaurant": "होटल / रेस्तरां",
    "Price: low to high": "दाम: कम से ज़्यादा",
    "Price: high to low": "दाम: ज़्यादा से कम",
    "Best quality first": "सर्वोत्तम गुणवत्ता पहले",
    "Largest lot first": "सबसे बड़ा माल पहले",

    # --- empty states and metric labels -------------------------------------------
    "Colour match": "रंग मिलान",
    "Colour match for ": "रंग मिलान — ",
    "Uniformity": "एकरूपता",
    "Uniformity across the lot": "पूरे माल में एकरूपता",
    "Freedom from defects": "दोषरहितता",
    "Unit size & consistency": "आकार और निरंतरता",
    "No listings yet": "अभी कोई सूची नहीं",
    "List your first crop lot and the AI will grade it instantly.":
        "अपनी पहली फसल दर्ज करें; एआई तुरंत उसका ग्रेड तय करेगा।",
    "No listings with this status.": "इस स्थिति में कोई सूची नहीं।",
    "No requirements found": "कोई मांग नहीं मिली",
    "No buyer requirement matches this filter right now.":
        "अभी इस फ़िल्टर से मेल खाती कोई मांग नहीं है।",
    "No requirements posted": "कोई मांग दर्ज नहीं",
    "Tell the platform what you need and matching farmers are notified automatically.":
        "आपको जो चाहिए वह दर्ज करें; मेल खाते किसानों को अपने आप सूचना चली जाती है।",
    "No lots match these filters": "इन फ़िल्टरों से मेल खाता माल नहीं",
    "Try widening the grade, price or district filter — or post a requirement so farmers come to you.":
        "ग्रेड, दाम या जिले का फ़िल्टर थोड़ा ढीला करें — या मांग दर्ज करें ताकि किसान आप तक आएं।",
    "Nothing to compare": "तुलना के लिए कुछ नहीं",
    "Tick the comparison box on two or more lots in the marketplace.":
        "बाज़ार में दो या अधिक माल पर तुलना बॉक्स चुनें।",
    "Nothing yet": "अभी कुछ नहीं",
    "Requests, offers and messages will appear here.":
        "अनुरोध, ऑफ़र और संदेश यहां दिखेंगे।",
    "Requests and offers will appear in this inbox.":
        "अनुरोध और ऑफ़र इस इनबॉक्स में दिखेंगे।",
    # --- added when template coverage was completed ---------------------
    "1 · Crop quality grading (computer vision)": "१ · फसल गुणवत्ता ग्रेडिंग (कंप्यूटर विज़न)",
    "1 · Photograph the lot": "१ · लॉट की फ़ोटो लें",
    "2 · AI grades and prices it": "२ · AI ग्रेड और दाम तय करता है",
    "2 · Price recommendation": "२ · मूल्य अनुशंसा",
    "3 · Certificates verified": "३ · प्रमाणपत्र सत्यापन",
    "3 · Demand prediction": "३ · माँग पूर्वानुमान",
    "4 · Deal directly": "४ · सीधा सौदा",
    "4 · OCMR certificate verification": "४ · OCMR प्रमाणपत्र सत्यापन",
    "A 0–100 demand index fuses four independent signals:": "०–१०० माँग सूचकांक चार स्वतंत्र संकेतों को जोड़ता है:",
    "A quality score and Grade A/B/C are assigned to the lot.": "लॉट को गुणवत्ता अंक और ग्रेड A/B/C दिया जाता है.",
    "A ten-check rule engine producing a confidence score.": "दस जाँचों का नियम-इंजन विश्वास अंक बनाता है.",
    "Why this matters.": "यह क्यों मायने रखता है.",
    "AI band": "AI बैंड",
    "AI fair band": "AI उचित मूल्य बैंड",
    "AI grade": "AI ग्रेड",
    "AI grading from a photo": "फ़ोटो से AI ग्रेडिंग",
    "AI quality grade": "AI गुणवत्ता ग्रेड",
    "Above band": "बैंड से ऊपर",
    "Above the fair band": "उचित बैंड से ऊपर",
    "Below band": "बैंड से नीचे",
    "Below the fair band": "उचित बैंड से नीचे",
    "Inside the fair band": "उचित बैंड के भीतर",
    "Within band": "बैंड के भीतर",
    "Under fair band": "उचित बैंड से कम",
    "Asking price": "माँगा गया दाम",
    "Recommended": "अनुशंसित",
    "Fair price today (Grade B)": "आज का उचित दाम (ग्रेड B)",
    "Fair-price check on every lot": "हर लॉट पर उचित मूल्य जाँच",
    "Grade A lots command about 18% more, Grade C about 18% less than this band.": "ग्रेड A के लॉट इस बैंड से लगभग १८% अधिक और ग्रेड C लगभग १८% कम दाम पाते हैं.",
    "Grade A only": "केवल ग्रेड A",
    "Grade B or better": "ग्रेड B या बेहतर",
    "Grade C or better": "ग्रेड C या बेहतर",
    "minimum grade": "न्यूनतम ग्रेड",
    "Minimum acceptable grade": "न्यूनतम स्वीकार्य ग्रेड",
    "Colour": "रंग",
    "Colour match for": "के लिए रंग मिलान —",
    "Colour score": "रंग अंक",
    "Defects": "दोष",
    "Defect-free score": "दोषमुक्त अंक",
    "Uniformity score": "एकरूपता अंक",
    "Size": "आकार",
    "value score": "मूल्य अंक",
    "Attribute": "विशेषता",
    "per quintal": "प्रति क्विंटल",
    "All deals": "सभी सौदे",
    "Browse all": "सभी देखें",
    "browse the marketplace": "बाज़ार देखें",
    "Market insights": "बाज़ार जानकारी",
    "Filter by grade, price and certificate": "ग्रेड, दाम और प्रमाणपत्र से छाँटें",
    "Side-by-side lot comparison": "लॉट की आमने-सामने तुलना",
    "Compare now": "अभी तुलना करें",
    "Compare up to four lots side by side before you commit.": "तय करने से पहले चार लॉट तक आमने-सामने तुलना करें.",
    "lot(s) selected for comparison (max 4)": "तुलना के लिए चुने गए लॉट (अधिकतम ४)",
    "Clear": "साफ़ करें",
    "Lots are ordered by": "लॉट इस क्रम में हैं —",
    "Lot": "लॉट",
    "Lot quantity": "लॉट मात्रा",
    "Lot status": "लॉट स्थिति",
    "Qty": "मात्रा",
    "Quantity (q)": "मात्रा (क्वि)",
    "Quantity (quintal)": "मात्रा (क्विंटल)",
    "Quantity available": "उपलब्ध मात्रा",
    "My price": "मेरा दाम",
    "Views": "व्यू",
    "Listed": "सूचीबद्ध",
    "Posted": "पोस्ट किया",
    "Manage": "प्रबंधन",
    "Delete listing": "लिस्टिंग हटाएँ",
    "Nearest market": "निकटतम मंडी",
    "Variety preferred": "पसंदीदा किस्म",
    "leave blank for any": "कोई भी — खाली छोड़ें",
    "e.g. Thompson Seedless, Bhagwa": "उदा. थॉमसन सीडलेस, भगवा",
    "e.g. Lasalgaon": "उदा. लासलगाँव",
    "e.g. Cold store, MIDC Satpur, Nashik": "उदा. कोल्ड स्टोर, MIDC सातपुर, नासिक",
    "Used for the price band.": "मूल्य बैंड के लिए उपयोग होता है.",
    "Pruning date, irrigation, spray schedule, packing available, transport…": "छँटाई तिथि, सिंचाई, छिड़काव कार्यक्रम, पैकिंग उपलब्ध, परिवहन…",
    "My requirements": "मेरी माँगें",
    "Requirement details": "माँग का विवरण",
    "Requirements that match one of your lots are shown first.": "आपके लॉट से मेल खाती माँगें पहले दिखाई गई हैं.",
    "Only ones I can fulfil": "केवल वे जो मैं पूरी कर सकूँ",
    "You can fulfil this": "इसे आप पूरा कर सकते हैं",
    "Offer one of my lots": "मेरा एक लॉट प्रस्तावित करें",
    "Which lot?": "कौन-सा लॉट?",
    "For requirement": "इस माँग के लिए",
    "Linked requirement": "जुड़ी हुई माँग",
    "Link to one of my requirements": "मेरी एक माँग से जोड़ें",
    "Open requirement": "माँग खोलें",
    "Open &amp; see matching lots": "खोलें और मेल खाते लॉट देखें",
    "Close, but not matching every condition": "लगभग, पर सभी शर्तें पूरी नहीं करते",
    "No farmer has offered against this requirement yet.": "इस माँग के लिए अभी तक किसी किसान ने प्रस्ताव नहीं दिया.",
    "You have not posted any requirement yet.": "आपने अभी तक कोई माँग पोस्ट नहीं की.",
    "Nothing matches yet. Post a requirement, or": "अभी कुछ मेल नहीं खाता. माँग पोस्ट करें, या",
    "Notes for farmers": "किसानों के लिए टिप्पणी",
    "Packing, payment terms, inspection, transport arrangement…": "पैकिंग, भुगतान शर्तें, निरीक्षण, परिवहन व्यवस्था…",
    "Organic produce only": "केवल जैविक उपज",
    "Verified quality certificate mandatory": "सत्यापित गुणवत्ता प्रमाणपत्र अनिवार्य",
    "Price range": "मूल्य सीमा",
    "Price range (₹ per quintal)": "मूल्य सीमा (₹ प्रति क्विंटल)",
    "Leave blank to invite open offers.": "खुले प्रस्तावों के लिए खाली छोड़ें.",
    "Budget": "बजट",
    "Needed by": "इस तिथि तक चाहिए",
    "Delivery": "डिलीवरी",
    "Delivery location": "डिलीवरी स्थान",
    "Delivery to": "यहाँ डिलीवरी",
    "District preferred": "पसंदीदा ज़िला",
    "Region": "क्षेत्र",
    "Post requirements, receive offers": "माँगें पोस्ट करें, प्रस्ताव पाएँ",
    "Matching lots appear on your requirement page, ranked by quality.": "मेल खाते लॉट आपकी माँग पेज पर गुणवत्ता क्रम में दिखते हैं.",
    "Farmers can send you offers against the requirement.": "किसान इस माँग के लिए आपको प्रस्ताव भेज सकते हैं.",
    "The requirement closes automatically once the full quantity is met.": "पूरी मात्रा मिलने पर माँग अपने आप बंद हो जाती है.",
    "Every farmer with that crop listed is notified.": "वह फसल सूचीबद्ध करने वाले हर किसान को सूचित किया जाता है.",
    "Setting a": "एक",
    "realistic price ceiling": "वास्तविक अधिकतम दाम",
    "Deal accepted.": "सौदा स्वीकार किया गया.",
    "Accepting reserves the lot and shares contact details with the other side.": "स्वीकार करने पर लॉट आरक्षित होता है और संपर्क विवरण दूसरे पक्ष को मिलता है.",
    "Arrange delivery and payment directly, then mark it complete.": "डिलीवरी और भुगतान सीधे तय करें, फिर पूर्ण चिह्नित करें.",
    "Cancel deal": "सौदा रद्द करें",
    "Withdraw this request": "यह अनुरोध वापस लें",
    "Open the request thread": "अनुरोध थ्रेड खोलें",
    "Open the full listing": "पूरी लिस्टिंग खोलें",
    "Opening message": "आरंभिक संदेश",
    "Response note": "उत्तर टिप्पणी",
    "Optional note — delivery date, packing, payment terms…": "वैकल्पिक टिप्पणी — डिलीवरी तिथि, पैकिंग, भुगतान शर्तें…",
    "Message to the buyer (packing, transport, when you can deliver)": "ख़रीदार को संदेश (पैकिंग, परिवहन, कब डिलीवरी दे सकते हैं)",
    "When you need delivery, packing requirement, payment terms…": "डिलीवरी कब चाहिए, पैकिंग आवश्यकता, भुगतान शर्तें…",
    "Your price (₹/q)": "आपका दाम (₹/क्वि)",
    "This thread is closed for new messages.": "इस थ्रेड पर नए संदेश नहीं भेजे जा सकते.",
    "No messages yet — say hello and agree the details.": "अभी कोई संदेश नहीं — नमस्ते कहें और विवरण तय करें.",
    "No buyer has requested this lot yet.": "इस लॉट के लिए अभी तक किसी ख़रीदार ने अनुरोध नहीं किया.",
    "No offers pending. Post a requirement and farmers will come to you.": "कोई प्रस्ताव लंबित नहीं. माँग पोस्ट करें, किसान आपके पास आएँगे.",
    "No pending requests right now.": "अभी कोई लंबित अनुरोध नहीं.",
    "The farmer can accept, decline or negotiate. Nothing is charged here.": "किसान स्वीकार, अस्वीकार या मोल-भाव कर सकता है. यहाँ कोई शुल्क नहीं.",
    "Phone and email are revealed once the deal is accepted.": "सौदा स्वीकार होने पर ही फ़ोन और ईमेल दिखते हैं.",
    "Contact details are shared once a request is accepted.": "अनुरोध स्वीकार होने पर संपर्क विवरण साझा होता है.",
    "wants": "को चाहिए",
    "offers": "प्रस्ताव देते हैं",
    "directly.": "सीधे.",
    "Certificate": "प्रमाणपत्र",
    "certificate": "प्रमाणपत्र",
    "Certificate file": "प्रमाणपत्र फ़ाइल",
    "Certificate number": "प्रमाणपत्र संख्या",
    "Certificate required": "प्रमाणपत्र आवश्यक",
    "Certificate type": "प्रमाणपत्र का प्रकार",
    "Certificate verification": "प्रमाणपत्र सत्यापन",
    "certificate verified": "प्रमाणपत्र सत्यापित",
    "Upload quality certificate": "गुणवत्ता प्रमाणपत्र अपलोड करें",
    "Upload &amp; verify": "अपलोड करें और सत्यापित करें",
    "Upload a better copy": "बेहतर प्रति अपलोड करें",
    "Remove this certificate": "यह प्रमाणपत्र हटाएँ",
    "Uploaded": "अपलोड किया",
    "Uploaded document": "अपलोड किया दस्तावेज़",
    "Verification checks": "सत्यापन जाँचें",
    "Verified at": "सत्यापन समय",
    "Valid until": "वैध तिथि तक",
    "Issue date": "जारी तिथि",
    "Issuing authority": "जारीकर्ता प्राधिकरण",
    "Holder on document": "दस्तावेज़ पर धारक",
    "Extracted fields": "निकाली गई जानकारी",
    "Raw OCR output": "मूल OCR पाठ",
    "Open PDF": "PDF खोलें",
    "View report": "रिपोर्ट देखें",
    "Report": "रिपोर्ट",
    "Full report": "पूरी रिपोर्ट",
    "confidence": "विश्वास",
    "No check details were recorded for this document.": "इस दस्तावेज़ के लिए जाँच विवरण दर्ज नहीं है.",
    "Buyers cannot send a request for this lot until one is verified.": "सत्यापन होने तक ख़रीदार इस लॉट के लिए अनुरोध नहीं भेज सकते.",
    "Send a request to see the full verification report": "पूरी सत्यापन रिपोर्ट देखने के लिए अनुरोध भेजें",
    "Not required": "आवश्यक नहीं",
    "What the OCMR check does": "OCMR जाँच क्या करती है",
    "Automatic rejection happens when": "स्वतः अस्वीकार तब होता है जब",
    "the document cannot be read at all;": "दस्तावेज़ बिलकुल पढ़ा नहीं जा सकता;",
    "the certificate has already expired;": "प्रमाणपत्र की अवधि समाप्त हो चुकी है;",
    "it refers to a different crop than this listing.": "वह इस लिस्टिंग से भिन्न फसल का है.",
    "Prepare": "तैयारी",
    "Read": "पठन",
    "Extract": "जानकारी निकालना",
    "Mark": "चिह्न",
    "Tamper check": "छेड़छाड़ जाँच",
    "Decide": "निर्णय",
    "Type": "प्रकार",
    "whole page": "पूरा पृष्ठ",
    "JPG, PNG or PDF, up to 8 MB. Scan or photograph the": "JPG, PNG या PDF, ८ MB तक. स्कैन करें या फ़ोटो लें —",
    "— denoise, deskew and binarise the scan.": "— स्कैन का शोर हटाएँ, झुकाव सीधा करें और बाइनरी बनाएँ.",
    "— Tesseract OCR extracts the text with a confidence score.": "— Tesseract OCR विश्वास अंक सहित पाठ निकालता है.",
    "— certificate number, issuing authority, issue and expiry dates, holder, crop and grade.": "— प्रमाणपत्र संख्या, जारीकर्ता, जारी व समाप्ति तिथि, धारक, फसल और ग्रेड.",
    "— any QR code is decoded and matched against the printed number.": "— QR कोड पढ़कर छपे नंबर से मिलाया जाता है.",
    "— error-level analysis flags digitally edited documents.": "— त्रुटि-स्तर विश्लेषण डिजिटल रूप से बदले दस्तावेज़ दिखाता है.",
    "— ten weighted checks produce a confidence score and a verdict.": "— दस भारित जाँचें विश्वास अंक और निर्णय देती हैं.",
    "— detect automatically —": "— स्वतः पहचानें —",
    "Image preparation: denoise, deskew, adaptive binarisation.": "छवि तैयारी: शोर हटाना, झुकाव सीधा करना, अनुकूली बाइनरी.",
    "Tesseract OCR with per-word confidence.": "प्रत्येक शब्द के विश्वास सहित Tesseract OCR.",
    "Field extraction by regular expression — number, issuer, dates, holder, crop, grade.": "रेगुलर एक्सप्रेशन से जानकारी निकालना — संख्या, जारीकर्ता, तिथियाँ, धारक, फसल, ग्रेड.",
    "QR / barcode detection and cross-check against the printed number.": "QR / बारकोड पहचान और छपे नंबर से मिलान.",
    "Error Level Analysis to flag digitally edited documents.": "डिजिटल रूप से बदले दस्तावेज़ दिखाने के लिए त्रुटि-स्तर विश्लेषण.",
    "Latest modal price": "नवीनतम मोडल दाम",
    "Period average": "अवधि का औसत",
    "Period range": "अवधि की सीमा",
    "Change over the period": "अवधि में बदलाव",
    "Price momentum": "मूल्य गति",
    "Supply pressure": "आपूर्ति दबाव",
    "Season": "मौसम",
    "Marketplace pull": "बाज़ार खिंचाव",
    "demand index": "माँग सूचकांक",
    "Demand &amp; market": "माँग और बाज़ार",
    "Demand forecast for your region": "आपके क्षेत्र के लिए माँग पूर्वानुमान",
    "Direction": "दिशा",
    "Trend": "रुझान",
    "Price now": "अभी का दाम",
    "Projected": "अनुमानित",
    "Range": "सीमा",
    "Week": "सप्ताह",
    "Weekly mandi arrivals (supply)": "साप्ताहिक मंडी आवक (आपूर्ति)",
    "Your district": "आपका ज़िला",
    "District-level price suggestion": "ज़िला स्तर पर मूल्य सुझाव",
    "No market data is available for this region yet. Run": "इस क्षेत्र के लिए अभी बाज़ार डेटा उपलब्ध नहीं. चलाएँ",
    "— last 30 days against the 90 days before.": "— पिछले ३० दिन बनाम उससे पहले के ९० दिन.",
    "— falling mandi arrivals with firm prices means tight supply.": "— दाम स्थिर रहते आवक घटना यानी आपूर्ति कम.",
    "— the crop's own lean/glut calendar.": "— उस फसल का अपना कमी/अधिकता कैलेंडर.",
    "— open buyer requirements against available listings on AgriVision itself.": "— AgriVision पर खुली माँगें बनाम उपलब्ध लिस्टिंग.",
    "— how much of the produce falls inside the healthy hue range for that crop, and how vivid it is.": "— उस फसल की स्वस्थ रंग सीमा में कितनी उपज आती है और रंग कितना गहरा है.",
    "— circular standard deviation of hue; a consistent lot grades higher because buyers pay for consistency.": "— रंग का वृत्तीय मानक विचलन; एकसमान लॉट बेहतर ग्रेड पाता है क्योंकि ख़रीदार एकरूपता का दाम देते हैं.",
    "— dark-spot and bruise ratio found by adaptive thresholding inside the produce mask.": "— उपज क्षेत्र में अनुकूली थ्रेशोल्ड से मिले काले धब्बे और चोट का अनुपात.",
    "— contour analysis of individual units and how consistent they are.": "— प्रत्येक इकाई का समोच्च विश्लेषण और उनकी एकरूपता.",
    "This lot has not been graded automatically.": "इस लॉट की स्वतः ग्रेडिंग नहीं हुई.",
    "Email": "ईमेल",
    "Email and mobile are your login IDs and cannot be changed here.": "ईमेल और मोबाइल ही आपके लॉगिन हैं; इन्हें यहाँ नहीं बदला जा सकता.",
    "Company / firm": "कंपनी / फ़र्म",
    "Taluka": "तालुका",
    "Drives your regional price and demand insights.": "इसी से आपके क्षेत्र के दाम और माँग तय होती है.",
    "Profile &amp; settings": "प्रोफ़ाइल और सेटिंग्स",
    "Already have an account?": "पहले से खाता है?",
    "Demo accounts": "डेमो खाते",
    "Farmer —": "किसान —",
    "Buyer —": "ख़रीदार —",
    "Get started": "शुरू करें",
    "Registration is free for both sides.": "दोनों पक्षों के लिए पंजीकरण मुफ़्त है.",
    "Access denied": "पहुँच अस्वीकृत",
    "Page not found": "पृष्ठ नहीं मिला",
    "Back to home": "मुख्य पृष्ठ पर वापस",
    "Back to the lot": "लॉट पर वापस",
    "The page you were looking for does not exist, or has been removed.": "आप जो पृष्ठ खोज रहे हैं वह मौजूद नहीं है या हटा दिया गया है.",
    "This page belongs to the other side of the platform, or to another user's account.": "यह पृष्ठ मंच के दूसरे पक्ष या किसी अन्य उपयोगकर्ता के खाते का है.",
    "Mark all read": "सभी पढ़े चिह्नित करें",
    "What happens when you submit": "सबमिट करने पर क्या होता है",
    "What happens next": "आगे क्या होता है",
    "Your photos are saved and analysed by the computer-vision grader.": "आपकी फ़ोटो सहेजी जाती हैं और कंप्यूटर-विज़न ग्रेडर से जाँची जाती हैं.",
    "The price band is recalculated using that grade.": "उस ग्रेड से मूल्य बैंड फिर से गणना होती है.",
    "If the crop needs a certificate, you will be asked to upload it next.": "यदि फसल को प्रमाणपत्र चाहिए तो आगे उसे अपलोड करने को कहा जाएगा.",
    "The crop type cannot be changed — create a new listing instead.": "फसल का प्रकार नहीं बदला जा सकता — इसके बजाय नई लिस्टिंग बनाएँ.",
    "Up to 5 photos, JPG or PNG, max 8 MB each. Daylight, close-up, produce filling the frame.": "अधिकतम ५ फ़ोटो, JPG या PNG, प्रत्येक ८ MB तक. दिन के उजाले में, पास से, फ़्रेम उपज से भरा हुआ.",
    "Adds a 15% premium to the suggested price.": "सुझाए दाम में १५% बढ़ोतरी करता है.",
    "— select the crop —": "— फसल चुनें —",
    "— not linked —": "— जुड़ा नहीं —",
    "Grading has not produced a result for this lot. Upload clearer photos and run the grader again.": "इस लॉट के लिए ग्रेडिंग का परिणाम नहीं मिला. अधिक स्पष्ट फ़ोटो अपलोड करें और ग्रेडिंग फिर चलाएँ.",
    "No buyer requirement matches your current lots. Keep your listings updated — matches appear here automatically.": "आपके मौजूदा लॉट से कोई माँग मेल नहीं खाती. लिस्टिंग अद्यतन रखें — मेल यहाँ स्वतः दिखेंगे.",
    "Buying smart on AgriVision": "AgriVision पर समझदारी से ख़रीद",
    "Every lot carries an AI grade — filter on it instead of travelling to inspect.": "हर लॉट पर AI ग्रेड है — देखने जाने के बजाय उसी से छाँटें.",
    "The fair-price band tells you when an asking price is above the market.": "माँगा दाम बाज़ार से ऊपर है या नहीं, यह उचित मूल्य बैंड बताता है.",
    "when you need export-grade paperwork.": "जब निर्यात स्तर के कागज़ात चाहिए.",
    "Check the demand index — it tells you whether to buy now or wait.": "माँग सूचकांक देखें — अभी ख़रीदें या रुकें, यह बताता है.",
    "Tick": "टिक करें",
    "View": "देखें",
    "View &amp; request": "देखें और अनुरोध करें",
    "Other": "अन्य",
    "For": "के लिए",
    "from ₹": "₹ से",
    "No listed lot currently satisfies all the conditions of this requirement. Relaxing the grade, the price ceiling or the certificate condition would widen the pool.": "अभी सूचीबद्ध कोई भी लॉट इस माँग की सभी शर्तें पूरी नहीं करता. ग्रेड, अधिकतम दाम या प्रमाणपत्र की शर्त थोड़ी ढीली करने पर अधिक विकल्प मिलेंगे.",
    "AgriVision is a direct farmer-to-buyer marketplace. Four AI modules sit behind the screens and do the work an agent or commission agent would otherwise do — grading the produce, fixing a fair price, judging demand and checking the paperwork.": "AgriVision किसान से ख़रीदार तक सीधा बाज़ार है. परदे के पीछे चार AI मॉड्यूल वही काम करते हैं जो आमतौर पर दलाल या आढ़तिया करता है — उपज की ग्रेडिंग, उचित दाम तय करना, माँग का आकलन और कागज़ात की जाँच.",
    "When a farmer uploads photos of a lot, OpenCV separates the produce from the background and measures four independent attributes:": "किसान द्वारा लॉट की फ़ोटो अपलोड करने पर OpenCV उपज को पृष्ठभूमि से अलग करता है और चार स्वतंत्र विशेषताएँ मापता है:",
    "These are fused into a 0–100 score and a Grade A / B / C verdict. A blurred or badly lit photo caps the score instead of inflating it, and the farmer is told to re-shoot.": "इन्हें मिलाकर ०–१०० अंक और ग्रेड A / B / C तय होता है. धुंधली या कम रोशनी वाली फ़ोटो से अंक बढ़ते नहीं बल्कि सीमित हो जाते हैं, और किसान को दोबारा फ़ोटो लेने को कहा जाता है.",
    "The suggested price starts from the median modal price of the last 45 days in the farmer's own district and is then adjusted by four multiplicative factors:": "सुझाया गया दाम किसान के अपने ज़िले में पिछले ४५ दिनों के माध्यक मोडल दाम से शुरू होता है और फिर चार गुणक कारकों से समायोजित होता है:",
    "Every factor is shown to the farmer with its reason, so the number is never a black box. The band width comes from that crop's historical volatility — wide for tomato, narrow for wheat.": "हर कारक अपने कारण सहित किसान को दिखाया जाता है, इसलिए यह आँकड़ा कभी रहस्य नहीं रहता. बैंड की चौड़ाई उस फसल के पुराने उतार-चढ़ाव से तय होती है — टमाटर के लिए चौड़ी, गेहूँ के लिए सँकरी.",
    "A least-squares trend over the weekly means, modulated by seasonality, gives a six-week price forecast with a widening confidence band.": "साप्ताहिक औसत पर न्यूनतम-वर्ग रुझान, मौसम के अनुसार समायोजित होकर, चौड़े होते विश्वास बैंड के साथ छह सप्ताह का मूल्य पूर्वानुमान देता है.",
    "OCMR — Optical Certificate &amp; Mark Recognition — is the six-stage pipeline that reads a quality certificate and decides whether to trust it:": "OCMR — ऑप्टिकल सर्टिफ़िकेट एंड मार्क रिकग्निशन — छह चरणों की वह प्रक्रिया है जो गुणवत्ता प्रमाणपत्र पढ़कर तय करती है कि उस पर भरोसा करें या नहीं:",
    "Expired certificates, wrong-crop certificates and unreadable scans are rejected outright; borderline cases are queued for manual review rather than silently passed.": "अवधि समाप्त, ग़लत फसल वाले या न पढ़े जा सकने वाले प्रमाणपत्र सीधे अस्वीकार होते हैं; संदिग्ध मामले चुपचाप पास करने के बजाय मानवीय जाँच के लिए रखे जाते हैं.",
    "A farmer who does not know the going rate is at the mercy of whoever is standing in the field. Transparent grading and a published fair-price band shift that balance — and a buyer gets a quality signal he can filter on before he ever travels to see the lot.": "चालू भाव न जानने वाला किसान खेत में खड़े व्यक्ति की मर्ज़ी पर निर्भर रहता है. पारदर्शी ग्रेडिंग और प्रकाशित उचित मूल्य बैंड यह संतुलन बदल देते हैं — और ख़रीदार को लॉट देखने जाने से पहले ही छाँटने का गुणवत्ता आधार मिल जाता है.",
    "fuses price momentum (38%), supply pressure from mandi arrivals (24%), the crop's seasonal calendar (18%) and AgriVision's own requirement-vs-listing balance (20%). 50 is a neutral market; above 70 is a seller's market.": "मूल्य गति (३८%), मंडी आवक से आपूर्ति दबाव (२४%), फसल का मौसमी कैलेंडर (१८%) और AgriVision पर माँग-बनाम-लिस्टिंग संतुलन (२०%) को जोड़ता है. ५० तटस्थ बाज़ार है; ७० से ऊपर विक्रेता का बाज़ार.",
    "Each bar is one week of arrivals — the quantity reaching the market. Falling arrivals with firm prices mean supply is tightening — usually a good time for a farmer to sell.": "हर स्तंभ एक सप्ताह की आवक है — बाज़ार तक पहुँचने वाली मात्रा. दाम स्थिर रहते आवक घटना यानी आपूर्ति कम हो रही है — किसान के लिए आमतौर पर बेचने का अच्छा समय.",
    "Based on": "आधार —",
    "Buying request": "ख़रीद अनुरोध",
    "Farmer offer": "किसान का प्रस्ताव",
    "Started by the": "शुरू करने वाला —",
    "Listed asking price is": "सूचीबद्ध माँगा गया दाम है",
    "Accept this": "इसे स्वीकारें",
    "Waiting for": "प्रतीक्षा —",
    "to respond": "के उत्तर की",
    "This trade is complete": "यह सौदा पूरा हो चुका है",
    "quintal at": "क्विंटल इस दाम पर",
    "This request was": "यह अनुरोध",
    "or better": "या बेहतर",
    "Register as": "के रूप में पंजीकरण करें",
    "Harvested": "कटाई",
    "On AgriVision since": "AgriVision पर तिथि से",
    "acre farm": "एकड़ खेत",
    "lots": "लॉट",
    "You have a pending request on this lot for": "इस लॉट पर आपका लंबित अनुरोध है —",
    "This lot is": "यह लॉट",
    "and cannot be requested": "है इसलिए अनुरोध नहीं किया जा सकता",
    "Scope": "दायरा",
    "Full": "पूरी",
    "report": "रिपोर्ट",
    "Offers received": "प्राप्त प्रस्ताव",
    "q at": "क्वि इस दाम पर",
    "Total": "कुल",
    "Lots that meet every condition": "सभी शर्तें पूरी करने वाले लॉट",
    "market": "बाज़ार",
    "Your ceiling of": "आपकी अधिकतम सीमा",
    "is below the current market price of": "मौजूदा बाज़ार भाव से कम है —",
    "up to": "तक",
    "open": "खुला",
    "OCMR verification": "OCMR सत्यापन",
    "weight": "भार",
    "views": "व्यू",
    "Mark as": "ऐसा चिह्नित करें —",
    "requires a verified quality certificate": "के लिए सत्यापित गुणवत्ता प्रमाणपत्र आवश्यक है",
    "No certificate uploaded yet": "अभी तक प्रमाणपत्र अपलोड नहीं",
    "No certificate needed for": "इसके लिए प्रमाणपत्र आवश्यक नहीं —",
    "Namaste": "नमस्ते",
    "Negotiable": "मोल-भाव योग्य",
    "projected change over": "इस अवधि में अनुमानित बदलाव —",
    "weeks": "सप्ताह",
    "Demand ranking for": "के लिए माँग क्रम —",
    "A listing must keep at least one photo.": "लिस्टिंग के लिए कम से कम एक फ़ोटो आवश्यक है.",
    "All notifications marked as read.": "सभी सूचनाएँ पढ़ी हुई चिह्नित कीं.",
    "Buying request sent to the farmer.": "ख़रीद अनुरोध किसान को भेजा गया.",
    "Certificate removed.": "प्रमाणपत्र हटाया गया.",
    "Choose the certificate file to upload.": "अपलोड करने के लिए प्रमाणपत्र फ़ाइल चुनें.",
    "Deal marked as completed.": "सौदा पूर्ण चिह्नित किया गया.",
    "Enter a quantity between 1 and {max:g} quintal.": "१ से {max:g} क्विंटल के बीच मात्रा दर्ज करें.",
    "Listing created. AI grade: {grade} ({score:.0f}/100).": "लिस्टिंग बन गई. AI ग्रेड: {grade} ({score:.0f}/१००).",
    "Listing deleted.": "लिस्टिंग हटाई गई.",
    "Listing marked as {status}.": "लिस्टिंग {status} चिह्नित की गई.",
    "Listing updated.": "लिस्टिंग अद्यतन हुई.",
    "Logged in as {name}.": "{name} के रूप में लॉगिन हुए.",
    "None of the photos could be saved. Please try again with JPG or PNG files.": "कोई भी फ़ोटो सहेजी नहीं जा सकी. कृपया JPG या PNG फ़ाइल के साथ दोबारा प्रयास करें.",
    "Only an accepted deal can be marked complete.": "केवल स्वीकृत सौदा ही पूर्ण चिह्नित किया जा सकता है.",
    "Only {left:g} quintal is left in this lot. Reject this request or ask the buyer to revise the quantity.": "इस लॉट में केवल {left:g} क्विंटल बचा है. यह अनुरोध अस्वीकार करें या ख़रीदार से मात्रा बदलने को कहें.",
    "Password updated.": "पासवर्ड बदला गया.",
    "Photo removed and the lot re-graded.": "फ़ोटो हटाई गई और लॉट की दोबारा ग्रेडिंग हुई.",
    "Please correct the highlighted fields.": "कृपया चिह्नित जानकारी ठीक करें.",
    "Profile updated.": "प्रोफ़ाइल अद्यतन हुई.",
    "Re-analysed: grade {grade} ({score:.0f}/100).": "दोबारा जाँचा: ग्रेड {grade} ({score:.0f}/१००).",
    "Request accepted. The lot is now reserved — use the chat to arrange delivery.": "अनुरोध स्वीकार किया. लॉट अब आरक्षित है — डिलीवरी तय करने के लिए चैट का उपयोग करें.",
    "Request declined.": "अनुरोध अस्वीकार किया.",
    "Request withdrawn.": "अनुरोध वापस लिया.",
    "Requirement closed.": "माँग बंद की गई.",
    "Requirement reopened.": "माँग फिर खोली गई.",
    "Requirement deleted.": "माँग हटाई गई.",
    "Requirement posted. Matching farmers have been notified.": "माँग पोस्ट की गई. मेल खाते किसानों को सूचित किया गया है.",
    "Requirement updated.": "माँग अद्यतन हुई.",
    "That notification does not belong to your account.": "वह सूचना आपके खाते की नहीं है.",
    "That requirement is already closed.": "वह माँग पहले ही बंद हो चुकी है.",
    "The new passwords do not match.": "नए पासवर्ड मेल नहीं खाते.",
    "This listing has no photos to analyse.": "इस लिस्टिंग में जाँचने के लिए फ़ोटो नहीं हैं.",
    "This lot is no longer available.": "यह लॉट अब उपलब्ध नहीं है.",
    "This lot needs a verified quality certificate before it can be traded.": "सौदे से पहले इस लॉट के लिए सत्यापित गुणवत्ता प्रमाणपत्र आवश्यक है.",
    "This request can no longer be withdrawn.": "यह अनुरोध अब वापस नहीं लिया जा सकता.",
    "This request has already been answered.": "इस अनुरोध का उत्तर पहले ही दिया जा चुका है.",
    "Unknown account type.": "अज्ञात खाता प्रकार.",
    "Upload up to 5 photos, JPG or PNG.": "अधिकतम ५ फ़ोटो अपलोड करें, JPG या PNG.",
    "Write a message before sending.": "भेजने से पहले संदेश लिखें.",
    "You already have a pending request on this lot.": "इस लॉट पर आपका पहले से लंबित अनुरोध है.",
    "You have already offered this lot against that requirement.": "आपने यह लॉट उस माँग के लिए पहले ही प्रस्तावित किया है.",
    "You have been logged out.": "आप लॉगआउट हो गए हैं.",
    "Your current password is incorrect.": "आपका मौजूदा पासवर्ड ग़लत है.",
    "Your offer has been sent to the buyer.": "आपका प्रस्ताव ख़रीदार को भेजा गया.",
    "closed": "बंद",
    "verified": "सत्यापित",
    "not_required": "आवश्यक नहीं",
    "request": "अनुरोध",
    "offer": "प्रस्ताव",
    "Listed asking price is {price} per quintal.": "सूचीबद्ध माँगा गया दाम {price} प्रति क्विंटल है.",
    "This offer is {amount} per quintal below the asking price ({pct}% less).": "यह प्रस्ताव माँगे गए दाम से {amount} प्रति क्विंटल कम है ({pct}% कम).",
    "This offer is {amount} per quintal above the asking price.": "यह प्रस्ताव माँगे गए दाम से {amount} प्रति क्विंटल अधिक है.",
    "The offer matches the asking price exactly.": "प्रस्ताव माँगे गए दाम से पूरी तरह मेल खाता है.",
    "Buyer dashboard": "ख़रीदार डैशबोर्ड",
    "Farmer dashboard": "किसान डैशबोर्ड",
    "Buyer requirements": "ख़रीदारों की माँगें",
    "Compare lots": "लॉट की तुलना",
    "Create an account": "खाता बनाएँ",
    "Profile": "प्रोफ़ाइल",
    "Verification report": "सत्यापन रिपोर्ट",
    "Farmer to buyer, directly": "किसान से सीधे ख़रीदार तक",
    "More buyers than sellers for": "विक्रेताओं से अधिक ख़रीदार —",
    "farmers have the upper hand.": "किसानों का पलड़ा भारी है.",
    "More listings than requirements — buyers can negotiate harder.": "माँगों से अधिक लिस्टिंग — ख़रीदार अधिक मोल-भाव कर सकते हैं.",
    "Supply and demand are balanced on the platform.": "मंच पर आपूर्ति और माँग संतुलित है.",
    "wants {qty:g} quintal of {crop}": "को {crop} के {qty:g} क्विंटल चाहिए",
    "at {price} per quintal · total {total}": "{price} प्रति क्विंटल · कुल {total}",
    "matches your {crop} lot ({qty:g} quintal, grade {grade})": "आपके {crop} लॉट से मेल खाता है ({qty:g} क्विंटल, ग्रेड {grade})",
}

CATALOGUES = {"mr": MR, "hi": HI}


# ======================================================================
# Runtime helpers
# ======================================================================
def get_locale() -> str:
    """
    Which language to render in, in priority order:

      1. ?lang= on this request   — lets a link force a language
      2. the session              — what the user last chose
      3. the logged-in user's saved preference
      4. the browser's Accept-Language header
      5. English

    The result is cached on `g` so a page rendering hundreds of strings does
    not re-resolve it hundreds of times.
    """
    if not has_request_context():
        return DEFAULT_LANGUAGE
    if getattr(g, "_locale", None):
        return g._locale

    lang = None
    arg = request.args.get("lang")
    if arg in LANGUAGES:
        lang = arg
    if not lang and session.get("lang") in LANGUAGES:
        lang = session["lang"]
    if not lang:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            if getattr(current_user, "language", None) in LANGUAGES:
                lang = current_user.language
    if not lang:
        lang = request.accept_languages.best_match(list(LANGUAGES)) or DEFAULT_LANGUAGE

    g._locale = lang
    return lang


_WS = re.compile(r"\s+")


def _key(text: str) -> str:
    """
    Normalise a lookup key by collapsing runs of whitespace.

    Templates wrap text where it sits, so the same sentence arrives with
    whatever indentation and line breaks the HTML happened to have:

        t("Upload up to 5 photos,
                   JPG or PNG.")

    Without normalising, that is a different key from the same sentence written
    on one line, and the catalogue would need an entry per indentation level.
    Collapsing whitespace means the catalogue holds one tidy single-line key
    and reformatting a template never silently drops a translation.
    """
    return _WS.sub(" ", text).strip()


def t(text: str, **kwargs) -> str:
    """
    Translate `text` into the current language.

    Falls back to the English source when a translation is missing, so a gap in
    the catalogue shows readable English rather than a broken key. A bad or
    missing format placeholder returns the unformatted string rather than
    raising — a template should never 500 because of a translation.
    """
    lang = get_locale()
    catalogue = CATALOGUES.get(lang)
    if not catalogue:
        out = text
    else:
        out = catalogue.get(text) or catalogue.get(_key(text)) or text

    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
    return out


def crop_name(name: str) -> str:
    """Crop names are stored in English in the database; show them translated."""
    return t(name)


def script_for(lang: str | None = None) -> str:
    return LANGUAGES.get(lang or get_locale(), {}).get("script", "latin")


def coverage() -> dict:
    """
    How complete each catalogue is, against the Marathi one as the reference.
    Used by tools/check_translations.py.
    """
    keys = set(MR) | set(HI)
    return {
        lang: {
            "translated": sum(1 for k in keys if k in CATALOGUES[lang]),
            "total": len(keys),
            "missing": sorted(k for k in keys if k not in CATALOGUES[lang]),
        }
        for lang in CATALOGUES
    }
