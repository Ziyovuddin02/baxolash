from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pandas as pd
import io
import os

# ReportLab PDF yaratish uchun
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.units import mm

# QR kod uchun
import qrcode


app = Flask(__name__)
app.secret_key = 'secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///evaluation.db'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    candidates = db.relationship('Candidate', backref='group_ref', lazy=True)

class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lastname = db.Column(db.String(50))
    firstname = db.Column(db.String(50))
    fathername = db.Column(db.String(50))  # ✅ yangi maydon
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    topic = db.Column(db.String(200))
    full_name = db.Column(db.String(100))
    passport = db.Column(db.String(20))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'))
    commission_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    score = db.Column(db.Integer)
    comment = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)

    candidate = db.relationship('Candidate', backref='evaluations')
    commission = db.relationship('User', backref='evaluations')

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role
            flash("✅ Tizimga muvaffaqiyatli kirdingiz!", "success")
            return redirect('/admin' if user.role == 'admin' else '/evaluate')
        else:
            flash("❌ Login yoki parol noto‘g‘ri!", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if session.get('role') != 'admin':
        return redirect('/')

    admin_user = User.query.get(session['user_id'])  # qo‘shildi

    candidates = Candidate.query.all()
    users = User.query.filter_by(role='commission').all()
    groups = Group.query.all()
    evaluations = Evaluation.query.all()

    total_candidates = len(candidates)
    total_commissions = len(users)
    evaluated_ids = {e.candidate_id for e in evaluations}
    evaluated_count = len(evaluated_ids)
    unevaluated_count = total_candidates - evaluated_count

    avg_scores = {}
    for c in candidates:
        candidate_evals = [e.score for e in c.evaluations]
        if candidate_evals:
            avg = sum(candidate_evals) / len(candidate_evals)
            percent = round((avg / 60) * 100)
            avg_scores[c.id] = percent
        else:
            avg_scores[c.id] = None

    if request.method == 'POST':
        if 'add_candidate' in request.form:
            lastname = request.form['lastname']
            firstname = request.form['firstname']
            group_id = request.form['group_id']
            topic = request.form['topic']
            full_name = f"{lastname} {firstname}"
            candidate = Candidate(
                lastname=lastname,
                firstname=firstname,
                group_id=group_id,
                topic=topic,
                full_name=full_name,
                passport="-"
            )
            db.session.add(candidate)
            db.session.commit()

        elif 'add_commission' in request.form:
            name = request.form['name']
            username = request.form['username']
            password = request.form['password']
            db.session.add(User(name=name, username=username, password=password, role='commission'))
            db.session.commit()

        elif 'add_group' in request.form:
            group_name = request.form['group_name']
            db.session.add(Group(name=group_name))
            db.session.commit()

        return redirect('/admin')

    return render_template('admin.html',
        admin_user=admin_user,  # qo‘shildi
        candidates=candidates,
        commissions=users,
        groups=groups,
        total_candidates=total_candidates,
        total_commissions=total_commissions,
        evaluated_count=evaluated_count,
        unevaluated_count=unevaluated_count,
        avg_scores=avg_scores
    )
@app.route('/upload_excel', methods=['POST'])
def upload_excel():
    if session.get('role') != 'admin':
        return redirect('/')

    file = request.files['excel_file']
    if not file:
        flash("❌ Fayl tanlanmadi!", "error")
        return redirect('/admin')

    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f"❌ Excel o‘qishda xatolik: {e}", "error")
        return redirect('/admin')

    required_cols = ['Familya', 'Ism', 'Otasining ismi', 'Guruh', 'Mavzu']
    if not all(col in df.columns for col in required_cols):
        flash("❌ Excel faylda quyidagi ustunlar bo‘lishi kerak: Familya, Ism, Otasining ismi, Guruh, Mavzu", "error")
        return redirect('/admin')

    for _, row in df.iterrows():
        lastname = str(row['Familya']).strip()
        firstname = str(row['Ism']).strip()
        fathername = str(row['Otasining ismi']).strip()
        group_name = str(row['Guruh']).strip()
        topic = str(row['Mavzu']).strip()
        full_name = f"{lastname} {firstname} {fathername}"

        group = Group.query.filter_by(name=group_name).first()
        if not group:
            group = Group(name=group_name)
            db.session.add(group)
            db.session.commit()

        candidate = Candidate(
            lastname=lastname,
            firstname=firstname,
            fathername=fathername,
            group_id=group.id,
            topic=topic,
            full_name=full_name,
            passport="-"
        )
        db.session.add(candidate)

    db.session.commit()
    flash("✅ Nomzodlar Excel orqali qo‘shildi", "success")
    return redirect('/admin')


@app.route('/evaluate', methods=['GET', 'POST'])
def evaluate():
    if session.get('role') != 'commission':
        return redirect('/')

    commission_id = session.get('user_id')
    commission_user = User.query.get(commission_id)  # qo‘shildi

    evaluated_ids = {e.candidate_id for e in Evaluation.query.filter_by(commission_id=commission_id).all()}
    candidates = Candidate.query.filter(~Candidate.id.in_(evaluated_ids)).all()
    groups = Group.query.all()

    if request.method == 'POST':
        candidate_id = int(request.form['candidate_id'])
        if Evaluation.query.filter_by(candidate_id=candidate_id, commission_id=commission_id).first():
            flash("❌ Bu nomzodni allaqachon baholagansiz!", "error")
            return redirect('/evaluate')

        comment = request.form.get('comment', '')

        try:
            scores = [
                int(request.form['criterion1']),
                int(request.form['criterion2']),
                int(request.form['criterion3']),
                int(request.form['criterion4']),
                int(request.form['criterion5']),
                int(request.form['criterion6']),
            ]
        except (ValueError, KeyError):
            flash("❌ Barcha mezonlarga to‘g‘ri raqam kiriting!", "error")
            return redirect('/evaluate')

        if any(score < 0 or score > 10 for score in scores):
            flash("❌ Har bir mezon uchun 0 dan 10 gacha ball qo‘yish mumkin!", "error")
            return redirect('/evaluate')

        total_score = sum(scores)
        percent = round((total_score / 60) * 100)

        db.session.add(Evaluation(
            candidate_id=candidate_id,
            commission_id=commission_id,
            score=total_score,
            comment=comment
        ))
        db.session.commit()
        flash(f"✅ Baho saqlandi: {total_score} ball ({percent}%)", "success")
        return redirect('/evaluate')

    evaluations = Evaluation.query.filter_by(commission_id=commission_id).all()
    return render_template('evaluate.html',
                           candidates=candidates,
                           groups=groups,
                           evaluations=evaluations,
                           commission_user=commission_user)  # qo‘shildi

from flask import jsonify

@app.route('/delete_candidate', methods=['POST'])
def delete_candidate():
    if not session.get('user_id') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Ruxsat yo‘q"})

    candidate_id = request.form['candidate_id']
    candidate = Candidate.query.get(candidate_id)

    if candidate:
        Evaluation.query.filter_by(candidate_id=candidate_id).delete()
        db.session.delete(candidate)
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Nomzod topilmadi"})


from flask import jsonify

@app.route('/delete_group', methods=['POST'])
def delete_group():
    if not session.get('user_id') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Ruxsat yo‘q"})

    group_id = request.form['group_id']
    group = Group.query.get(group_id)
    if group:
        for candidate in group.candidates:
            Evaluation.query.filter_by(candidate_id=candidate.id).delete()
            db.session.delete(candidate)
        db.session.delete(group)
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Guruh topilmadi"})


@app.route('/delete_commission', methods=['POST'])
def delete_commission():
    if not session.get('user_id') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Ruxsat yo‘q"})

    commission_id = request.form['commission_id']
    user = User.query.get(commission_id)

    if user and user.role == 'commission':
        Evaluation.query.filter_by(commission_id=commission_id).delete()
        db.session.delete(user)
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Komissiya a’zosi topilmadi"})




@app.route('/export/excel')
def export_excel():
    if session.get('role') != 'admin':
        return redirect('/')

    group_id = request.args.get('group_id')
    data = []

    evaluations = Evaluation.query.all()
    if group_id:
        candidates = Candidate.query.filter_by(group_id=group_id).all()
        candidate_ids = [c.id for c in candidates]
        evaluations = Evaluation.query.filter(Evaluation.candidate_id.in_(candidate_ids)).all()

    for e in evaluations:
        cand = Candidate.query.get(e.candidate_id)
        comm = User.query.get(e.commission_id)
        group = Group.query.get(cand.group_id)
        percent = round((e.score / 60) * 100)
        data.append({
            'Familya': cand.lastname,
            'Ism': cand.firstname,
            'Guruh': group.name if group else "-",
            'Mavzu': cand.topic,
            'Bahosi': e.score,
            'Foiz': f"{percent}%",
            'Komissiya': comm.name,
            'Izoh': e.comment,
            'Sana': e.evaluated_at.strftime('%Y-%m-%d')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='hisobot.xlsx', as_attachment=True)



@app.route('/export/pdf')
def export_pdf():
    if session.get('role') != 'admin':
        return redirect('/')

    group_id = request.args.get('group_id')
    group = Group.query.get(group_id)
    candidates = Candidate.query.filter_by(group_id=group_id).all()

    # Ma’lumotlarni tayyorlash
    candidate_list = []
    for cand in candidates:
        ev = Evaluation.query.filter_by(candidate_id=cand.id).first()
        candidate_list.append({
            "full_name": cand.full_name,
            "score": ev.score if ev else None
        })

    qr_url = f"http://127.0.0.1:5000/static/reports/{group.name}.pdf"
    output_path = f"static/reports/{group.name}.pdf"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    elements = []

    # Style sozlamalari
    title_style = ParagraphStyle('Title', fontName='Times-Bold', fontSize=14, alignment=TA_CENTER, leading=18)
    subtitle_style = ParagraphStyle('Subtitle', fontName='Times-Roman', fontSize=12, alignment=TA_CENTER, leading=16)
    normal_left = ParagraphStyle('Left', fontName='Times-Roman', fontSize=12, alignment=TA_LEFT)
    normal_bold = ParagraphStyle('BoldLeft', fontName='Times-Bold', fontSize=12, alignment=TA_LEFT)

    # Sarlavhalar
    elements.append(Paragraph("TOSHKENT VILOYATI PEDAGOGIK MAHORAT MARKAZI", title_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("Ma’naviy va ma’rifiy ishlar bo‘yicha direktor o‘rinbosarlari malaka oshirish kursi tinglovchilari", subtitle_style))
    elements.append(Paragraph("tomonidan yakuniy nazoratda (suhbatda) qayd etilgan natijalar", subtitle_style))
    elements.append(Spacer(1, 20))

    # Jadval
    data = [["T/R", "Talabaning F.I.SH", "Guruh raqami", "Sinov natijasi\n(maks.ball-60)"]]
    for i, item in enumerate(candidate_list, 1):
        data.append([
            str(i),
            item["full_name"],
            group.name,
            item["score"] if item["score"] is not None else "Chetlatilgan"
        ])

    table = Table(data, colWidths=[25*mm, 75*mm, 35*mm, 45*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 40))

    # Komissiya a’zolari va imzo qatori
    komis_table = Table([
        [Paragraph("Komissiya raisi <b>T. Ortiqov</b>", normal_left), "___________________"],
        [Paragraph("Komissiya a’zosi <b>X. Bo‘ronboyev</b>", normal_left), "___________________"],
        [Paragraph("Komissiya a’zosi <b>D. Aripova</b>", normal_left), "___________________"]
    ], colWidths=[100*mm, 70*mm])
    komis_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Times-Roman'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(komis_table)
    elements.append(Spacer(1, 20))

    # QR kod
    qr_img = qrcode.make(qr_url)
    qr_io = io.BytesIO()
    qr_img.save(qr_io, format='PNG')
    qr_io.seek(0)
    elements.append(Image(qr_io, width=80, height=80))

    doc.build(elements)
    buffer.seek(0)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(buffer.read())

    buffer.seek(0)
    return send_file(buffer, download_name="hisobot.pdf", as_attachment=True)



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(name='Admin', username='admin', password='123', role='admin'))
            db.session.commit()
    app.run(debug=True)

