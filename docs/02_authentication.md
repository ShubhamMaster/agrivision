# 02 · Authentication and dual-role access control

**Section goal:** separate logins for farmers and buyers, with each side locked
out of the other's screens.

---

## 1. Files in this section

| File | Responsibility |
|---|---|
| `app/routes/auth.py` | register / login / logout / profile |
| `app/utils.py` | the `@role_required` decorator and field validators |
| `app/models.py` → `User` | password hashing, `user_loader` |
| `app/templates/auth/register_choice.html` | pick farmer or buyer |
| `app/templates/auth/register.html` | the sign-up form (adapts to the role) |
| `app/templates/auth/login.html` | login form |
| `app/templates/auth/profile.html` | view/edit profile, change password |

---

## 2. Routes

| Method | URL | Purpose |
|---|---|---|
| GET | `/auth/register` | role chooser — two cards |
| GET/POST | `/auth/register/<role>` | the actual sign-up form |
| GET/POST | `/auth/login` | log in with email **or** mobile |
| GET | `/auth/logout` | end the session |
| GET/POST | `/auth/profile` | edit details; change password |

---

## 3. How passwords are stored

```python
def set_password(self, raw_password):
    self.password_hash = generate_password_hash(raw_password)

def check_password(self, raw_password):
    return check_password_hash(self.password_hash, raw_password)
```

`generate_password_hash` (Werkzeug) produces a **PBKDF2-SHA256** hash with a
random per-user salt and 600,000 iterations, stored as a single string:

```
pbkdf2:sha256:600000$NR2xK9fV$8c1d...e7
└ algorithm ┘ └iterations┘ └salt ┘ └hash┘
```

Three properties matter:

1. **One-way.** You cannot recover the password from the hash.
2. **Salted.** Two users with the same password get different hashes, so a
   precomputed rainbow table is useless.
3. **Slow by design.** 600,000 iterations make brute-forcing expensive.

The raw password never touches the database, the logs, or a template. Even the
form-redisplay code in `register()` filters it out:

```python
form = {k: clean(v) for k, v in request.form.items() if k != "password"}
```

---

## 4. Registration

### Step 1 — choose a side

`/auth/register` shows two cards. This matters because the two forms differ:

| Farmer form | Buyer form |
|---|---|
| farm size (acres) | company / firm name |
| | buyer type (Trader / Exporter / Retailer / Processor / FPO / Hotel) |
| | GST number |

Both collect name, email, mobile, password and **location**.

### Step 2 — validation

Every field is validated server-side. Client-side `required` attributes are
convenience only — they are trivially bypassed, so the server never trusts them.

```python
errors["email"]    = validate_email(email)      # regex
errors["phone"]    = validate_phone(phone)      # ^[6-9]\d{9}$  (Indian mobile)
errors["password"] = validate_password(password)  # ≥6 chars, not all digits
if password != confirm: errors["confirm_password"] = "..."
if not district:        errors["district"] = "District is required…"
```

Then **uniqueness**:

```python
if User.query.filter_by(email=email).first():
    errors["email"] = "An account with this email already exists."
```

The database also has `unique=True` on both columns — the query gives a friendly
message, the constraint is the actual guarantee against a race between two
simultaneous sign-ups.

**Why district is mandatory:** every price and demand query filters on it. A user
without a district silently falls back to the state average, and the single most
valuable feature of the platform — *your district's* price — degrades to a
national number.

### Step 3 — create and log in

```python
user = User(full_name=..., email=..., role=role, ...)
user.set_password(password)
db.session.add(user); db.session.commit()
login_user(user)
return redirect(url_for(f"{role}.dashboard"))
```

The redirect is built from the role string, so a farmer lands on
`/farmer/dashboard` and a buyer on `/buyer/dashboard`.

---

## 5. Login

### Email or mobile, either works

```python
user = (User.query.filter_by(email=identifier).first()
        or User.query.filter_by(phone=identifier).first())
```

A farmer is far more likely to remember his mobile number than an email address.

### Deliberately vague error message

```python
if not user or not user.check_password(password):
    error = "Incorrect email/mobile or password."
```

One message for both failures. Saying "no such user" would let an attacker
enumerate which emails are registered — a standard account-enumeration leak.

### Role mismatch

If the form posts a role tab that disagrees with the stored role, the user is
told which side the account belongs to rather than being bounced to the wrong
dashboard.

### Safe `next` redirect

```python
nxt = request.args.get("next")
if nxt and nxt.startswith("/") and not nxt.startswith("//"):
    return redirect(nxt)
```

A user who hits a protected page is sent to `/auth/login?next=/farmer/crops/3`
and returned there afterwards. The two checks prevent an **open redirect**:
without them, `?next=https://evil.example` or `?next=//evil.example` would send
the freshly-authenticated user to an attacker's site.

---

## 6. Session management — Flask-Login

Flask-Login stores only the **user id** in the signed session cookie and rebuilds
the user object on every request:

```python
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
```

The cookie is signed with `SECRET_KEY`, so a user cannot edit it to become
someone else — any tampering invalidates the signature.

`current_user` is then available everywhere, including inside templates, which
is how the navbar knows whether to show "My Crops" or "Marketplace".

---

## 7. Access control — `@role_required`

The heart of the dual-login requirement, in `app/utils.py`:

```python
def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request_path()))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator
```

Used as:

```python
@farmer_bp.route("/dashboard")
@role_required("farmer")
def dashboard(): ...
```

### Two different failures, two different responses

| Situation | Response | Why |
|---|---|---|
| Not logged in | redirect to login with `next` | They may legitimately want this page. |
| Logged in, wrong role | **403 page** | Silently redirecting a buyer to the farmer dashboard would be baffling. Tell them plainly. |

### Why `@wraps(view)` matters

Without it, every decorated view would be named `wrapper`, and Flask would raise
`View function mapping is overwriting an existing endpoint` on the second route
registered. `@wraps` copies the original function's name and docstring onto the
wrapper.

---

## 8. Three layers of authorisation

Role checking alone is not enough. Farmer A must not read farmer B's lot even
though both are farmers. The project applies three layers:

| Layer | Mechanism | Stops |
|---|---|---|
| 1. Authentication | `@login_required` / `@role_required` | anonymous access |
| 2. Role | `@role_required("farmer")` | a buyer opening farmer screens |
| 3. Ownership | `_own_crop()`, `_own_req()`, `_access()` | farmer A opening farmer B's lot by editing the URL |

Layer 3 looks like this:

```python
def _own_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    if crop.farmer_id != current_user.id:
        abort(403)
    return crop
```

This is an **IDOR** (Insecure Direct Object Reference) defence — the single most
common web vulnerability in student projects, where `/crops/5` happily shows you
someone else's data. `tests/test_routes.py` asserts the 403 explicitly.

For deals the rule is different again, because two people legitimately share one
object:

```python
def _access(deal_id):
    deal = DealRequest.query.get_or_404(deal_id)
    if current_user.id not in (deal.farmer_id, deal.buyer_id):
        abort(403)
    return deal
```

---

## 9. Profile and password change

One route handles both, dispatched on a hidden `action` field. Changing a
password requires the **current** password:

```python
if not current_user.check_password(current):
    flash("Your current password is incorrect.", "danger")
```

Without that, anyone who finds an unattended logged-in browser could lock the
real owner out of the account.

Email and phone are shown disabled — they are login identifiers, and changing
them needs an OTP verification flow that is out of scope.

---

## 10. Data flow

```
POST /auth/register/farmer
   ├── validate every field                    → errors? re-render with messages
   ├── check email and phone are unique        → errors? re-render
   ├── User(...)  +  set_password()            → PBKDF2 hash
   ├── db.session.commit()
   ├── login_user(user)                        → signed cookie with user id
   └── redirect /farmer/dashboard

GET /farmer/crops/3
   ├── @role_required("farmer")
   │      ├── not authenticated → /auth/login?next=/farmer/crops/3
   │      └── role == 'buyer'   → 403
   ├── _own_crop(3) → crop.farmer_id != current_user.id → 403
   └── render the page
```

---

## 11. Known limitations (be honest about these in a viva)

- **No CSRF tokens.** Flask-WTF would add them; the forms are plain HTML here.
- **No email/OTP verification.** `is_verified` exists but nothing sets it.
- **No password reset.** Needs an email backend.
- **No rate limiting on login.** Flask-Limiter would cap attempts per IP.
- **HTTP in development.** Production needs HTTPS, or the session cookie travels
  in clear text.

---

## 12. Viva questions

**Q. How are passwords stored?**
As PBKDF2-SHA256 hashes with a random per-user salt and 600,000 iterations,
produced by Werkzeug's `generate_password_hash`. The raw password is never
stored. Verification re-hashes the input with the stored salt and compares.

**Q. What is a salt and why does it matter?**
Random data mixed into the password before hashing. It makes two identical
passwords hash differently, which defeats precomputed rainbow tables.

**Q. How do you keep a buyer out of the farmer section?**
The `@role_required("farmer")` decorator on every farmer view checks
`current_user.role` and calls `abort(403)` on a mismatch. The check is on the
server, so hiding the nav link is cosmetic, not security.

**Q. A farmer changes the URL from `/farmer/crops/3` to `/farmer/crops/9`, which
belongs to someone else. What happens?**
`_own_crop()` compares `crop.farmer_id` with `current_user.id` and aborts with
403. That is an IDOR defence, and there is a test asserting it.

**Q. Why is the login error message vague?**
To prevent account enumeration. A distinct "no such user" message would let an
attacker discover which emails are registered.

**Q. What is the `next` parameter and why is it validated?**
It remembers where the user was heading before being asked to log in. It is
checked to be a relative path so it cannot be used as an open redirect to an
external site.

**Q. What does Flask-Login actually store in the cookie?**
Only the user id, in a cryptographically signed cookie. `user_loader` reloads
the user from the database on each request. Tampering breaks the signature.

**Q. What is `@wraps` for?**
It copies the wrapped function's name and metadata onto the wrapper. Without it
every decorated view would be called `wrapper` and Flask would reject the
duplicate endpoint names.
