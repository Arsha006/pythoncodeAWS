import os
import uuid

import boto3
import pymysql
from botocore.config import Config
from flask import Flask, render_template, render_template_string, request
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ---- Settings come from environment variables (never hardcode secrets) ----
DB_HOST = os.environ["DB_HOST"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# No access keys here: boto3 uses the EC2 instance's IAM role automatically.
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(signature_version="s3v4"),
)


def get_db():
    """Open a fresh database connection for each request."""
    return pymysql.connect(
        host=DB_HOST,
        port=3306,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connect_timeout=10,
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register():
    name = request.form["name"]
    email = request.form["email"]
    course = request.form["course"]
    photo = request.files.get("photo")

    if photo is None or photo.filename == "":
        return "Please choose a photo.", 400

    # Unique key so two students with the same filename don't overwrite each other
    s3_key = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"

    s3.upload_fileobj(photo, S3_BUCKET_NAME, s3_key)

    # The bucket is private, so we store only the S3 key (not a public URL).
    db = get_db()
    try:
        with db.cursor() as cursor:
            sql = """
            INSERT INTO students (name, email, course, photo_url)
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (name, email, course, s3_key))
        db.commit()
    finally:
        db.close()

    return 'Student Registered Successfully. <a href="/students">View students</a>'


@app.route("/students")
def students():
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT id, name, email, course, photo_url FROM students")
            rows = cursor.fetchall()
    finally:
        db.close()

    people = []
    for row_id, name, email, course, s3_key in rows:
        # Temporary link, valid for 5 minutes
        photo_link = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=300,
        )
        people.append(
            {"id": row_id, "name": name, "email": email, "course": course, "photo": photo_link}
        )

    return render_template_string(
        """
        <h2>Registered Students</h2>
        <table border="1" cellpadding="8">
          <tr><th>ID</th><th>Name</th><th>Email</th><th>Course</th><th>Photo</th></tr>
          {% for p in people %}
          <tr>
            <td>{{ p.id }}</td><td>{{ p.name }}</td><td>{{ p.email }}</td>
            <td>{{ p.course }}</td>
            <td><img src="{{ p.photo }}" width="100"></td>
          </tr>
          {% endfor %}
        </table>
        <p><a href="/">Back to form</a></p>
        """,
        people=people,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
