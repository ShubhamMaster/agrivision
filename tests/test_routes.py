"""
AgriVision — end-to-end route test.

Runs the whole application through Flask's test client against the seeded
database: every page both roles can reach, plus the full deal lifecycle
(request -> accept -> message -> complete) and access-control checks.

    python tests/test_routes.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                      # noqa: E402
from app.models import Crop, DealRequest, Requirement, User   # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=""):
    (PASS if condition else FAIL).append(label)
    mark = "  ok  " if condition else " FAIL "
    print(f"[{mark}] {label}" + (f"  — {detail}" if detail and not condition else ""))


def get(client, url, expect=200, label=None):
    r = client.get(url, follow_redirects=False)
    ok = r.status_code == expect
    check(label or f"GET {url}", ok, f"got {r.status_code}, expected {expect}")
    return r


def login(client, email, password):
    return client.post("/auth/login",
                       data={"identifier": email, "password": password},
                       follow_redirects=True)


def main():
    app = create_app()
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        farmer = User.query.filter_by(email="ramesh@agrivision.in").first()
        buyer = User.query.filter_by(email="sahyadri@agrivision.in").first()
        assert farmer and buyer, "Run `python seed.py` first."
        farmer_id, buyer_id = farmer.id, buyer.id
        crop = Crop.query.filter_by(farmer_id=farmer_id, status="available").first()
        crop_id = crop.id
        other_crop = Crop.query.filter(Crop.farmer_id != farmer_id,
                                       Crop.status == "available").first()
        other_crop_id = other_crop.id
        buyable = Crop.query.filter(
            Crop.status == "available", Crop.farmer_id != farmer_id).all()
        buyable = [c for c in buyable
                   if not c.certificate_required or c.certificate_status == "verified"]
        buyable_id = buyable[0].id
        req_id = Requirement.query.filter_by(buyer_id=buyer_id, status="open").first().id
        cert_crop = Crop.query.filter(Crop.certificate_status == "verified").first()
        cert_id = cert_crop.certificates[0].id

    print("\n" + "=" * 62)
    print("PUBLIC PAGES")
    print("=" * 62)
    with app.test_client() as c:
        get(c, "/")
        get(c, "/about")
        get(c, "/auth/login")
        get(c, "/auth/register")
        get(c, "/auth/register/farmer")
        get(c, "/auth/register/buyer")
        get(c, "/no-such-page", 404, "GET /no-such-page returns 404")
        r = c.get("/farmer/dashboard")
        check("anonymous user is redirected away from /farmer/dashboard",
              r.status_code in (302, 401), f"got {r.status_code}")

    print("\n" + "=" * 62)
    print("FARMER SIDE")
    print("=" * 62)
    with app.test_client() as c:
        r = login(c, "ramesh@agrivision.in", "farmer123")
        check("farmer logs in", b"Dashboard" in r.data or b"Namaste" in r.data)

        get(c, "/farmer/dashboard")
        get(c, "/farmer/crops")
        get(c, "/farmer/crops?status=available")
        get(c, "/farmer/crops/new")
        get(c, f"/farmer/crops/{crop_id}")
        get(c, f"/farmer/crops/{crop_id}/edit")
        get(c, f"/farmer/crops/{other_crop_id}", 403,
            "farmer cannot open another farmer's lot (403)")
        get(c, f"/farmer/crops/{crop_id}/certificate")
        get(c, f"/farmer/certificates/{cert_id}")
        get(c, "/farmer/requirements")
        get(c, "/farmer/requirements?matching=1")
        get(c, "/insights/")
        get(c, "/insights/crop/Grapes")
        get(c, "/insights/api/trend?crop=Grapes")
        get(c, "/deals/")
        get(c, "/notifications")
        get(c, "/auth/profile")
        get(c, "/buyer/browse", 403, "farmer cannot reach the buyer marketplace (403)")

        # live price helper
        r = c.post("/farmer/api/price-suggestion",
                   json={"crop_name": "Grapes", "district": "Nashik", "state": "Maharashtra"})
        js = r.get_json()
        check("price-suggestion API returns a band",
              r.status_code == 200 and js.get("ok") and js["min"] < js["recommended"] < js["max"],
              str(js)[:120])

        # create a listing with a real uploaded image
        img_path = None
        with app.app_context():
            from config import Config
            files = [f for f in os.listdir(Config.CROP_IMAGE_DIR) if f.endswith(".jpg")]
            img_path = os.path.join(Config.CROP_IMAGE_DIR, files[0])
        with open(img_path, "rb") as fh:
            blob = fh.read()

        r = c.post("/farmer/crops/new", data={
            "crop_name": "Tomato", "variety": "Test Variety", "quantity": "25",
            "expected_price": "1500", "state": "Maharashtra", "district": "Nashik",
            "market": "Pimpalgaon", "description": "Route test lot.",
            "photos": (io.BytesIO(blob), "test.jpg"),
        }, content_type="multipart/form-data", follow_redirects=True)
        check("farmer creates a listing and it is graded", b"AI grade" in r.data or b"Grade" in r.data)

        with app.app_context():
            new_crop = Crop.query.filter_by(crop_name="Tomato", variety="Test Variety").first()
            check("new listing received an AI grade and a price band",
                  new_crop is not None and new_crop.ai_grade is not None
                  and new_crop.ai_price_min is not None,
                  f"grade={getattr(new_crop, 'ai_grade', None)}")
            new_crop_id = new_crop.id

        r = c.post(f"/farmer/crops/{new_crop_id}/regrade", follow_redirects=True)
        check("re-run grading works", r.status_code == 200)
        r = c.post(f"/farmer/crops/{new_crop_id}/status/withdrawn", follow_redirects=True)
        check("status change works", r.status_code == 200)
        r = c.post(f"/farmer/crops/{new_crop_id}/delete", follow_redirects=True)
        check("listing delete works", r.status_code == 200)

    print("\n" + "=" * 62)
    print("BUYER SIDE")
    print("=" * 62)
    with app.test_client() as c:
        r = login(c, "sahyadri@agrivision.in", "buyer123")
        check("buyer logs in", r.status_code == 200)

        get(c, "/buyer/dashboard")
        get(c, "/buyer/browse")
        get(c, "/buyer/browse?crop=Grapes&grade=B&sort=quality")
        get(c, "/buyer/browse?organic=1&certified=1")
        get(c, f"/buyer/crop/{buyable_id}")
        get(c, "/buyer/requirements")
        get(c, "/buyer/requirements/new")
        get(c, f"/buyer/requirements/{req_id}")
        get(c, f"/buyer/requirements/{req_id}/edit")
        get(c, "/insights/")
        get(c, "/deals/")
        get(c, "/farmer/dashboard", 403, "buyer cannot reach the farmer dashboard (403)")

        with app.app_context():
            ids = [c_.id for c_ in Crop.query.filter_by(status="available").limit(3).all()]
        get(c, "/buyer/compare?" + "&".join(f"id={i}" for i in ids), 200,
            "GET /buyer/compare with three lots")

        # post a requirement
        r = c.post("/buyer/requirements/new", data={
            "crop_name": "Wheat", "quantity": "75", "min_grade": "B",
            "price_min": "2200", "price_max": "2800", "state": "Maharashtra",
            "district": "Nashik", "delivery_location": "Test warehouse",
            "notes": "Route test requirement.",
        }, follow_redirects=True)
        check("buyer posts a requirement", b"Wheat" in r.data)

        # send a buying request
        r = c.post(f"/buyer/crop/{buyable_id}/request", data={
            "quantity": "5", "offered_price": "1000", "message": "Route test request.",
        }, follow_redirects=True)
        check("buyer sends a buying request", b"request" in r.data.lower())

        with app.app_context():
            deal = (DealRequest.query.filter_by(crop_id=buyable_id, buyer_id=buyer_id)
                    .order_by(DealRequest.id.desc()).first())
            check("deal row was created", deal is not None)
            deal_id = deal.id
            deal_farmer_email = deal.farmer.email

        get(c, f"/deals/{deal_id}")
        r = c.post(f"/deals/{deal_id}/accept", follow_redirects=True)
        check("buyer cannot accept their own request", r.status_code == 403,
              f"got {r.status_code}")

    print("\n" + "=" * 62)
    print("DEAL LIFECYCLE (farmer answers)")
    print("=" * 62)
    with app.test_client() as c:
        login(c, deal_farmer_email, "farmer123")
        get(c, f"/deals/{deal_id}")

        r = c.post(f"/deals/{deal_id}/message", data={"body": "Testing the chat."},
                   follow_redirects=True)
        check("message posted to the thread", b"Testing the chat." in r.data)

        r = c.post(f"/deals/{deal_id}/accept", data={"note": "Accepted in the route test."},
                   follow_redirects=True)
        check("farmer accepts the request", r.status_code == 200)
        with app.app_context():
            d = DealRequest.query.get(deal_id)
            check("deal is accepted and the lot is reserved",
                  d.status == "accepted" and d.crop.status == "reserved",
                  f"status={d.status} crop={d.crop.status}")

        r = c.post(f"/deals/{deal_id}/complete", follow_redirects=True)
        check("deal can be completed", r.status_code == 200)
        with app.app_context():
            d = DealRequest.query.get(deal_id)
            check("completed deal reduced the lot quantity",
                  d.status == "completed", f"status={d.status}")

    print("\n" + "=" * 62)
    print("ACCESS CONTROL ON SOMEONE ELSE'S DEAL")
    print("=" * 62)
    with app.test_client() as c:
        login(c, "kavita@agrivision.in", "farmer123")
        get(c, f"/deals/{deal_id}", 403, "a third party cannot open the deal (403)")

    print("\n" + "=" * 62)
    print("LANGUAGES")
    print("=" * 62)
    with app.test_client() as c:
        # Devanagari is returned as UTF-8 bytes; compare against encoded text.
        r = c.get("/lang/mr?next=/", follow_redirects=True)
        check("switching to Marathi renders Devanagari",
              "मुख्यपृष्ठ".encode() in r.data, "footer 'Home' not translated")
        check("the html lang attribute follows the language",
              b'<html lang="mr"' in r.data)

        r = c.get("/lang/hi?next=/", follow_redirects=True)
        check("switching to Hindi renders Devanagari",
              "मुख्य पृष्ठ".encode() in r.data)

        r = c.get("/lang/en?next=/", follow_redirects=True)
        check("switching back to English", b'<html lang="en"' in r.data
              and b"Sell your harvest" in r.data)

        r = c.get("/lang/xx?next=/", follow_redirects=True)
        check("an unknown language code is refused safely", r.status_code == 200)

        # The language switch must not become an open redirect.
        r = c.get("/lang/mr?next=https://evil.example/", follow_redirects=False)
        check("language switch cannot redirect off-site",
              "evil.example" not in r.headers.get("Location", ""),
              r.headers.get("Location", ""))

    with app.test_client() as c:
        login(c, "ramesh@agrivision.in", "farmer123")
        c.get("/lang/mr")
        r = c.get("/farmer/dashboard")
        check("a signed-in farmer sees the dashboard in Marathi",
              "डॅशबोर्ड".encode() in r.data)
        with app.app_context():
            u = User.query.filter_by(email="ramesh@agrivision.in").first()
            check("the language choice is saved on the account", u.language == "mr",
                  f"language={u.language}")
        c.get("/lang/en")

    print("\n" + "=" * 62)
    print("ONBOARDING GUIDE")
    print("=" * 62)
    with app.test_client() as c:
        r = c.post("/auth/register/farmer", data={
            "full_name": "Guide Test Farmer", "email": "guidetest@agrivision.in",
            "phone": "9876511111", "password": "test1234",
            "confirm_password": "test1234", "state": "Maharashtra",
            "district": "Nashik",
        }, follow_redirects=False)
        check("registration sends a new user to the guide",
              r.status_code == 302 and "/guide" in r.headers.get("Location", ""),
              r.headers.get("Location", ""))

        r = c.get("/guide")
        check("the guide shows farmer steps to a farmer",
              b"Photograph your crop" in r.data and b"Post what you need" not in r.data)

        with app.app_context():
            u = User.query.filter_by(email="guidetest@agrivision.in").first()
            check("the guide is unseen before it is dismissed", not u.onboarding_seen)

        r = c.post("/guide/done", data={"skip": "1"}, follow_redirects=False)
        check("skipping the guide goes to the dashboard",
              "/farmer/dashboard" in r.headers.get("Location", ""),
              r.headers.get("Location", ""))

        with app.app_context():
            u = User.query.filter_by(email="guidetest@agrivision.in").first()
            check("skipping marks the guide as seen", u.onboarding_seen)
            gid = u.id

        get(c, "/guide", 200, "the guide stays reachable after being skipped")

    with app.test_client() as c:
        r = c.post("/auth/register/buyer", data={
            "full_name": "Guide Test Buyer", "email": "guidebuyer@agrivision.in",
            "phone": "9876522222", "password": "test1234",
            "confirm_password": "test1234", "state": "Maharashtra",
            "district": "Pune",
        }, follow_redirects=True)
        check("the guide shows buyer steps to a buyer",
              b"Post what you need" in r.data and b"Photograph your crop" not in r.data)

        r = c.post("/guide/done", follow_redirects=False)
        check("finishing the guide goes to the marketplace",
              "/buyer/browse" in r.headers.get("Location", ""),
              r.headers.get("Location", ""))

    with app.app_context():
        for email in ("guidetest@agrivision.in", "guidebuyer@agrivision.in"):
            u = User.query.filter_by(email=email).first()
            if u:
                from app.extensions import db as _db
                _db.session.delete(u)
        from app.extensions import db as _db
        _db.session.commit()

    print("\n" + "=" * 62)
    print(f"RESULT:  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print("   failed:", f)
    print("=" * 62 + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
