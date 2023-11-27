from flask import Flask, flash, render_template, redirect, url_for, request, session
from models import db, UserTable, Comment, CommentSection, Party, Post, get_comments_of_post, insert_BLOB_user
import os
from datetime import datetime, timedelta
from time import time, sleep 
import boto3
from boto3 import logging
from bucket_wrapper import BucketWrapper
from flask_bcrypt import Bcrypt
from flask_session import Session
from werkzeug.security import generate_password_hash

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

    # Either path will load all posts, however only the videos on cloud will load on prod and vice-versa
    if app.config['FLASK_ENV'] == 'prod':
        return render_template('index.html', posts=posts, distribution_url=distribution_url, user_table=UserTable)    
    else:
        for post in posts:
            try:
                if f'{post.video_id}.mp4' in os.listdir(f'{app.config["UPLOAD_PATH"]}/videos'):
                    post_index = os.listdir(f'{app.config["UPLOAD_PATH"]}/videos').index(f'{post.video_id}.mp4')
                    videos.append(os.listdir(f'{app.config["UPLOAD_PATH"]}/videos')[post_index])   
                    user_name = UserTable.query.get(post.user_id).user_name
            except FileNotFoundError as e:
                print(e)
                print(f'{post.video_id}.mp4 is not in videos.')
        return render_template('index.html', posts=posts, distribution_url=f'{app.config["UPLOAD_PATH"]}/', UserTable=UserTable) 

@app.context_processor
def comment_get():
    return dict(get_post_comments=get_comments_of_post)


@app.get('/<int:post_id>')
def get_single_post(post_id: int):
    post = Post.query.get(post_id)

    comment_section = CommentSection.query.filter_by(post_id=post.id).first()
    comments = list(Comment.query.filter_by(comment_section_id=comment_section.id).all())
    
    if app.config['FLASK_ENV'] == 'prod':
        return render_template('single_post.html', post=post, distribution_url=distribution_url, comment_section=comment_section, comments=comments, UserTable=UserTable)
    else:
        return render_template('single_post.html', post=post, distribution_url=f'{app.config["UPLOAD_PATH"]}/', comment_section=comment_section, comments=comments, UserTable=UserTable)

@app.post('/<int:post_id>')
def post_comment(post_id: int):
    post = Post.query.get(post_id)
    message = request.form.get('comment')
    cs = CommentSection.query.filter_by(post_id=post.id).first()
    print(cs)
    comment = Comment(cs.id, session.get('id'), message)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('get_single_post', post_id=post.id))

@app.route('/user_prof')
def user_prof():
    return None #rendertemplate('user_profile.html')

@app.route('/settings')
def settings_page():
        
    if not session.get('id'):
        return redirect('/login')


    if app.config['FLASK_ENV'] == 'prod':
        pfp = bucket_wrapper.get_object(s3_client, f'{app.config["PFP_PATH"]}testpfp.png')

    current_user = UserTable.query.get(session.get('id'))

    if session.get('id') == current_user.id:
        print(current_user)
        print(current_user.id)


    pfps = bucket_wrapper.get_objects(s3_client) 
    print(pfps)
    print(f'{distribution_url}{pfps[0]}/images/pfp/testpfp.png')

    return render_template('settings.html', profile_pic_url=pfps, distribution_url=distribution_url, private_setting=current_user.private)

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
        first_name = request.form.get('first_name')

        if not first_name or first_name == '':
            flash('Enter a first name')
            return redirect(url_for('get_login'))
            
        last_name = request.form.get('last_name')

        if not last_name or last_name == '':
            flash('Enter a last name')
            return redirect(url_for('get_login'))

        email = request.form.get('email')

        if not email or email == '':
            flash('Enter an email')
            return redirect(url_for('get_login'))
            
        phone = request.form.get('phone')

        if not phone or phone == '':
            flash('Enter a phone number')
            return redirect(url_for('get_login'))
        
        username = request.form.get('username')

        if not username or username == '':
            flash('Enter a username')
            return redirect(url_for('get_login'))
        
        raw_password = request.form.get('password')

        if not raw_password or raw_password == '':
            flash('Enter a password')
            return redirect(url_for('get_login'))

        hashed_password = bcrypt.generate_password_hash(raw_password, 16).decode()

        new_user = UserTable(first_name, last_name, username, hashed_password, email, phone)
        db.session.add(new_user)
        db.session.commit()

        session['id'] = new_user.id
    
        flash('Successfully Signed Up')
        return redirect(url_for('homepage'))
    except:
        flash('Unable to Sign Up\nTry Again Later.')
        return redirect(url_for('get_login'))
    
@app.route('/update_credentials', methods=['POST'])
def update_credentials():
    user_id = session.get('id')

    # Fetch user from database
    user = UserTable.query.get(user_id)

    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('login_page'))

    try:
        new_email = request.form.get('email')
        new_phone = request.form.get('phone')
        new_password = request.form.get('password')
        private_setting = request.form.get('private') == 'on'
        
        changes_made = False

        if new_email and new_email != '':
            user.email = new_email
            changes_made = True

        if new_phone and new_phone != '':
            user.phone = new_phone
            changes_made = True

        if new_password and new_password != '':
            hashed_password = bcrypt.generate_password_hash(new_password, 16).decode()
            user.password = hashed_password
            changes_made = True

        if user.private != private_setting:
            user.private = private_setting
            changes_made = True

        if changes_made:
            db.session.commit()
            flash('Credentials updated successfully', 'success')
        else:
            flash('No changes detected', 'error')

        return redirect(url_for('settings_page'))

    except Exception as e:
        flash(f'Unable to update credentials: {e}', 'error')
        return redirect(url_for('settings_page'))
