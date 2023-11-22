from flask import Flask, flash, render_template, redirect, url_for, request, session
from models import db, UserTable, Comment, CommentSection, Party, Post, insert_BLOB_user
import os
from datetime import datetime, timedelta
from time import time, sleep 
import boto3
from boto3 import logging
from bucket_wrapper import BucketWrapper
from flask_bcrypt import Bcrypt
from flask_session import Session

from blueprints.jam_session.jam_sessions import jam_sessions_bp
from blueprints.uploader.upload import upload_bp

app = Flask(__name__)
app.app_context().push()

app.config.from_pyfile('config.py')

app.register_blueprint(jam_sessions_bp, url_prefix='/sessions')
app.register_blueprint(upload_bp, url_prefix='/upload')

bcrypt = Bcrypt(app)

Session(app)

app.permanent_session_lifetime = timedelta(minutes=30)

db.init_app(app)

# Create AWS session
aws = boto3.Session(
                aws_access_key_id= os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key= os.getenv('AWS_SECRET_ACCESS_KEY'),
            )

# Create clients from session
s3_client = aws.client('s3')
s3_resource = aws.resource('s3')
s3_distr = aws.client('cloudfront')
s3_transcoder = aws.client('elastictranscoder', 'us-east-1')

# Get CloudFront distribution
distribution = s3_distr.get_distribution(Id="E2CLJ3WM17V7LF")

# URL for distribution, append object keys to url to access 
distribution_url = f'https://{distribution["Distribution"]["DomainName"]}/'

# Get specific bucket from s3
riff_bucket = s3_resource.Bucket('riffbucket-itsc3155')

# Wrap bucket to access specific funcionality
bucket_wrapper = BucketWrapper(riff_bucket)

boto3.set_stream_logger('', logging.INFO)
logger = logging.getLogger()

@app.route('/')
def homepage():

    if not session.get('id'):
        return redirect('/login')
    
    print(f'Logged in as {UserTable.query.get(session.get("id")).user_name}')
    
    videos = []
    posts = Post.query.all()

    if app.config['FLASK_ENV'] == 'prod':
        bucket_videos = bucket_wrapper.get_videos(s3_client) 
        for post in posts:
            try: 
                if f'videos/{post.id}.mp4' in bucket_videos:
                    videos.append(f'videos/{post.id}.mp4')
            except FileNotFoundError as e:
                print(f'videos/{post.id}.mp4 is not in videos.')
                
        print(videos)
        return render_template('index.html', videos=videos, distribution_url=distribution_url)    
    else:

        for post in posts:
            if f'{post.id}.mp4' in os.listdir(app.config['UPLOAD_PATH']):
                post_index = os.listdir(app.config['UPLOAD_PATH']).index(f'{post.id}.mp4')
                videos.append(os.listdir(app.config['UPLOAD_PATH'])[post_index])            
            
        return render_template('index.html', videos=videos, distribution_url=f'{app.config["UPLOAD_PATH"]}/') 


@app.route('/user_prof')
def user_prof():
    return None #rendertemplate('user_profile.html')

@app.route('/settings')
def settings_page():

    if not session.get('id'):
        return redirect('/login')
    
    if app.config['FLASK_ENV'] == 'prod':
        pfp = bucket_wrapper.get_object(s3_client, f'{app.config["PFP_PATH"]}testpfp.png')

        profile_pic_path = 'profile_pic.jpg'
        if os.path.exists(profile_pic_path):
            profile_pic_url = '/' + profile_pic_path

        profile_pic_path = os.path.join('images', 'pfp.png')  
        full_path = os.path.join(app.static_folder, profile_pic_path)
        if os.path.exists(full_path):
            profile_pic_url = url_for('static', filename=profile_pic_path)

        else:
            profile_pic_url = url_for('static', filename='testpfp.jpg') 

        return render_template('settings.html', profile_pic_url=profile_pic_url, distribution_url=distribution_url, pfp=pfp)
    else:
        
        return render_template('settings.html', profile_pic_url=None, distribution_url=None, pfp=None)



@app.route('/update_profile_pic', methods=['POST'])
def update_profile_pic():
    if 'profile_pic' not in request.files:
        return redirect(request.url)

    file = request.files['profile_pic']

    if file.filename == '':
        return redirect(request.url)

    if file:  
        user_id = ...  
        insert_BLOB_user(user_id, file)
        return redirect(url_for('settings_page'))


@app.get('/login')
def get_login():
    if session.get('id'):
        return redirect('/')
    try:
        current_user = UserTable.query.get(session.get('id'))

        if session.get('id') == current_user.id:
            redirect(url_for('homepage'))
    except Exception as e:
        print(e)


    return render_template('login.html')

@app.post('/login')
def login():
        try:
            username = request.form.get('username')

            if not username or username == '':
                flash('Enter a username')
                return redirect(url_for('get_login'))
            
            raw_password = request.form.get('password')

            if not raw_password or raw_password == '':
                flash('Enter a password')
                return redirect(url_for('get_login'))

            current_user = UserTable.query.filter_by(user_name=username).first()

            if current_user:
                check_pass = bcrypt.check_password_hash(current_user.password, raw_password)
            
            if not check_pass:
                flash('Incorrect Username or Password')
                return redirect(url_for('get_login'))
        
            session['id'] = current_user.id

            flash('Successfully Logged In')
            return redirect(url_for('homepage'))
        except:
            sleep(3)
            flash('Incorrect Username or Password')
            return redirect(url_for('get_login'))
        

@app.post('/logout')
def logout():
    try:
        session.clear()
        return redirect(url_for('get_login'))
    except Exception as e:
        print(e)
        return redirect(url_for('homepage'))
    
    


@app.post('/signup')
def sign_up():

    try:
        username = request.form.get('username')

        if not username or username == '':
            flash('Enter a username')
            return redirect(url_for('get_login'))
        
        raw_password = request.form.get('password')

        if not raw_password or raw_password == '':
            flash('Enter a password')
            return redirect(url_for('get_login'))

        hashed_password = bcrypt.generate_password_hash(raw_password, 16).decode()

        new_user = UserTable('John', 'Doe', username, hashed_password, 'johnd@gmail.com', 111_222_3333)
        db.session.add(new_user)
        db.session.commit()

        session['id'] = new_user.id
    
        flash('Successfully Signed Up')
        return redirect(url_for('homepage'))
    except:
        flash('Unable to Sign Up\nTry Again Later.')
        return redirect(url_for('get_login'))


