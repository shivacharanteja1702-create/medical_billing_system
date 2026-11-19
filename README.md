# MediBill — Updated Medical Billing System

## Features
- Staff registration and login (passwords are hashed)
- Patient and medical service management
- Invoice generation with multiple services, quantities, discount and initial payment
- Atomic SQLite invoice saving: the invoice and its line items are committed together or rolled back together
- Billing history, invoice detail, printing and additional payments
- Dashboard and invoice-wise financial reports calculated from saved database records
- Responsive hospital-themed UI with a medical reception background

## Run on Windows
1. Extract this ZIP.
2. Open the `medical_billing_system` folder in VS Code.
3. Open Terminal in that folder.
4. Run:
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   py -m pip install -r requirements.txt
   py app.py
   ```
5. Open http://127.0.0.1:5000

If PowerShell blocks virtual-environment activation, skip activation and run:
```powershell
py -m pip install --user -r requirements.txt
py app.py
```

## Demo login
Username: `admin`
Password: `admin123`

You can also create a staff account from the Registration page.

## Important
- The SQLite database is created automatically as `medical_billing.db` beside `app.py`.
- Existing database files should be backed up before replacing project files. This ZIP does not include a database, so your existing patient and billing records are not overwritten by extraction.
- Replace `SECRET_KEY` in `app.py` before any real deployment.
- This is a student demonstration project. Do not store real patient medical information or use it as a production healthcare billing system without security, privacy, access-control and compliance review.
