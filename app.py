from flask import Flask, render_template, request, jsonify
import os
import re
import docx2txt
import PyPDF2
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx'}

# In-memory companies list
companies = []

# Load skill keywords from dictionary-style or list-style JSON
def load_skill_keywords():
    skills_file = "skills.json"
    if os.path.exists(skills_file):
        with open(skills_file, "r") as f:
            try:
                skills_data = json.load(f)
                if isinstance(skills_data, dict):
                    return list(skills_data.keys())
                elif isinstance(skills_data, list):
                    return skills_data
                else:
                    return []
            except json.JSONDecodeError:
                return []
    return []

SKILL_KEYWORDS = load_skill_keywords()

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_text(file_path):
    text = ""
    if file_path.endswith(".pdf"):
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
    elif file_path.endswith(".docx"):
        text = docx2txt.process(file_path)
    return text

def extract_cgpa(text):
    match = re.search(r'(?:CGPA|GPA)[:\s]*([0-9]+\.[0-9]+)', text, re.I)
    return float(match.group(1)) if match else None

def extract_skills(text):
    text_lower = text.lower()
    return list(set(skill for skill in SKILL_KEYWORDS if skill in text_lower))

def match_companies(student_skills, student_cgpa):
    matched_companies = []
    student_skills_set = set(skill.lower().strip() for skill in student_skills)

    for company in companies:
        company_skills = set(skill.lower().strip() for skill in company.get('skills', []))
        if not company_skills:
            continue

        overlap = student_skills_set.intersection(company_skills)
        if not overlap:
            continue

        match_ratio = len(overlap) / len(company_skills)

        matched_companies.append({
            'company_name': company['name'],
            'job_role': company['jobRole'],
            'min_cgpa': company['min_cgpa'],
            'matched_skills': list(overlap),
            'match_score': round(match_ratio * 100, 2),
            'cgpa_ok': student_cgpa >= company['min_cgpa']
        })

    matched_companies.sort(key=lambda x: x['match_score'], reverse=True)
    return matched_companies

# Load companies from persistent JSON file
def load_companies_from_json():
    global companies
    companies_file = "companies.json"
    if os.path.exists(companies_file):
        with open(companies_file, "r") as f:
            try:
                companies = json.load(f)
                for company in companies:
                    company['skills'] = [skill.strip().lower() for skill in company.get('skills', [])]
                    company['name'] = company['name'].strip().lower()
            except json.JSONDecodeError:
                companies = []

def save_companies_to_json():
    with open("companies.json", "w") as f:
        json.dump(companies, f, indent=4)

# Routes
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/student')
def student():
    return render_template("student.html")

@app.route('/company')
def company():
    return render_template("company.html")

@app.route('/register_company', methods=['POST'])
def register_company():
    data = request.get_json()
    company_name = data['name'].strip().lower()

    new_company = {
        'name': company_name,
        'jobRole': data['jobRole'],
        'skills': [skill.strip().lower() for skill in data['skills']],
        'min_cgpa': float(data['minCgpa']),
        'experience': data['experience']
    }

    updated = False
    for i, comp in enumerate(companies):
        if comp['name'] == company_name:
            companies[i] = new_company
            updated = True
            break

    if not updated:
        companies.append(new_company)

    save_companies_to_json()

    return jsonify({
        'message': f"Company {'updated' if updated else 'registered'} successfully",
        'total_companies': len(companies)
    })

@app.route('/add_skills', methods=['POST'])
def add_skills():
    try:
        data = request.get_json(force=True)
        company_name = data.get('name', '').strip().lower()
        new_skills = [s.strip().lower() for s in data.get('skills', [])]

        if not company_name or not new_skills:
            return jsonify({'error': 'Missing company name or skills list'}), 400

        skills_file = "skills.json"
        if os.path.exists(skills_file):
            with open(skills_file, "r") as f:
                try:
                    skills_data = json.load(f)
                except json.JSONDecodeError:
                    skills_data = {}
        else:
            skills_data = {}

        # Update skill map
        for skill in new_skills:
            if skill in skills_data:
                if company_name not in skills_data[skill]:
                    skills_data[skill].append(company_name)
            else:
                skills_data[skill] = [company_name]

        with open(skills_file, "w") as f:
            json.dump(skills_data, f, indent=4)

        global SKILL_KEYWORDS
        SKILL_KEYWORDS = list(skills_data.keys())

        return jsonify({'message': f"Skills for {company_name} mapped successfully."})

    except Exception as e:
        return jsonify({'error': f"Failed to map skill: {str(e)}"}), 500


@app.route('/process_resume', methods=['POST'])
def process_resume():
    name = request.form.get('name')
    form_cgpa = request.form.get('cgpa')
    file = request.files.get('resume')

    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid or missing file'}), 400

    filename = secure_filename(file.filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    text = extract_text(file_path)
    resume_skills = extract_skills(text)
    resume_cgpa = extract_cgpa(text) or float(form_cgpa or 0.0)

    matched = match_companies(resume_skills, resume_cgpa)

    return jsonify({
        'recommendations': matched,
        'message': f"Resume processed successfully for {name}"
    })

@app.route('/companies', methods=['GET'])
def get_companies():
    sorted_companies = sorted(companies, key=lambda c: c['name'])
    return jsonify(sorted_companies)

@app.route('/skills_map', methods=['GET'])
def get_skills_map():
    skills_file = "skills.json"
    if os.path.exists(skills_file):
        with open(skills_file, "r") as f:
            try:
                skills_data = json.load(f)
                return jsonify(skills_data)
            except json.JSONDecodeError:
                return jsonify({})
    return jsonify({})

if __name__ == "__main__":
    os.makedirs("uploads", exist_ok=True)
    load_companies_from_json()
    app.run(debug=True)
