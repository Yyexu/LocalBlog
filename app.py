from flask import Flask, render_template, redirect, url_for, request, flash
from models import db, User, Article, Category, Tag, Comment
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
import os
import requests
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

## AI key
DEEPSEEK_API_KEY = "sk-9217291767384ccbaceeb57bc804a710"  # 替换为你申请的 Key
DEEPSEEK_BASE_URL = "https://api.deepseek.com/chat/completions"

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

UPLOAD_FOLDER = 'static/uploads/users'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# --- 1. 编辑器图片上传接口 ---
@app.route('/upload_article_img', methods=['POST'])
@login_required
def upload_article_img():
    file = request.files.get('editormd-image-file')  # Editor.md 默认的文件名 key
    if not file:
        return {'success': 0, 'message': '未找到文件'}

    # 存放到 static/uploads/users/<id>/articles/
    upload_path = get_user_upload_path(current_user.id, 'articles')
    filename = secure_filename(file.filename)
    file.save(os.path.join(upload_path, filename))

    # 返回 Editor.md 要求的格式
    return {
        'success': 1,
        'message': '上传成功',
        'url': f'/static/uploads/users/{current_user.id}/articles/{filename}'
    }


# --- 2. 个人头像上传接口 ---
@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar_file')
    if file:
        upload_path = get_user_upload_path(current_user.id, 'avatar')
        filename = "avatar_" + secure_filename(file.filename)
        save_path = os.path.join(upload_path, filename)
        file.save(save_path)

        # 更新数据库
        current_user.avatar_url = f'/static/uploads/users/{current_user.id}/avatar/{filename}'
        db.session.commit()
    return "OK", 200


def get_user_upload_path(user_id, folder_name):
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id), folder_name)
    if not os.path.exists(path):
        os.makedirs(path)
    return path


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 首页重定向到登录
@app.route('/')
def index():
    # 查询所有已发布的文章（is_draft=False），按时间倒序排列
    # 如果你想只看自己的，可以加 filter_by(user_id=current_user.id)
    # 但通常博客首页是看所有人的公开文章
    articles = Article.query.filter_by(is_draft=False).order_by(Article.update_time.desc()).all()
    return render_template('index.html', articles=articles)


# 注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')  # 实际开发建议用 generate_password_hash
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('注册成功！', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


# 登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        # --- 核心修改：校验哈希密码 ---
        # 第一个参数是数据库存的密文，第二个参数是用户输入的明文
        if user and check_password_hash(user.password, password):
            login_user(user)
            user.last_login = datetime.now()
            db.session.commit()
            flash("登陆成功！", 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


# 个人面板
@app.route('/dashboard')
@login_required
def dashboard():
    # 统计信息
    article_count = Article.query.filter_by(user_id=current_user.id).count()
    category_count = Category.query.filter_by(user_id=current_user.id).count()
    user_articles = Article.query.filter_by(user_id=current_user.id).order_by(Article.id.desc()).all()
    tag_count = Tag.query.filter_by(user_id=current_user.id).count()

    articles = Article.query.filter_by(user_id=current_user.id).order_by(Article.update_time.desc()).all()

    return render_template('dashboard.html',
                           article_count=article_count,
                           category_count=category_count,
                           tag_count=tag_count,
                           articles=articles)


# 登出
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('登出成功！', 'success')
    return redirect(url_for('login'))


@app.route('/article/new', methods=['GET', 'POST'])
@login_required
def create_article():
    if request.method == 'POST':
        title = request.form.get('title') or "未命名草稿"
        summary_text = request.form.get('summary')
        content = request.form.get('content')
        category_name = request.form.get('category').strip()
        tag_names = request.form.get('tags').replace('，', ',').split(',')
        post_status = request.form.get('post_status', 'published')

        # 1. 处理分类
        category = Category.query.filter_by(name=category_name, user_id=current_user.id).first()
        if not category and category_name:
            category = Category(name=category_name, user_id=current_user.id)
            db.session.add(category)
            db.session.commit()

        # 2. 创建文章对象 (先不填 cover_url)
        new_article = Article(
            title=title,
            summary=summary_text,
            content=content,
            user_id=current_user.id,
            category_id=category.id if category else None,
            is_draft=(post_status == 'draft')
        )

        # 3. 重点：先将对象加入 session 并 flush
        db.session.add(new_article)
        # flush 的作用是向数据库请求生成 ID，但还不正式提交事务
        db.session.flush()

        # 4. 现在有了 ID，处理封面上传
        cover_file = request.files.get('cover_file')
        if cover_file and cover_file.filename != '':
            cover_path = save_article_cover(cover_file, new_article.id)
            new_article.cover_url = cover_path  # 将路径补填回去

        # 5. 处理标签
        for t_name in tag_names:
            t_name = t_name.strip()
            if not t_name: continue
            tag = Tag.query.filter_by(name=t_name, user_id=current_user.id).first()
            if not tag:
                tag = Tag(name=t_name, user_id=current_user.id)
                db.session.add(tag)
                db.session.commit()
            new_article.tags.append(tag)

        # 6. 正式提交所有修改
        db.session.commit()

        flash('内容已自动保存到草稿箱' if post_status == 'draft' else '文章发布成功！')
        return redirect(url_for('dashboard'))

    user_categories = Category.query.filter_by(user_id=current_user.id).all()
    return render_template('write_article.html', categories=user_categories)


# --- 删除文章 ---
@app.route('/article/delete/<int:article_id>')
@login_required
def delete_article(article_id):
    article = Article.query.filter_by(id=article_id, user_id=current_user.id).first_or_404()

    db.session.delete(article)
    db.session.commit()
    flash('文章已删除')
    return redirect(url_for('dashboard'))


@app.route('/user/<int:user_id>')
def public_profile(user_id):
    # 获取被查看的用户信息
    user = User.query.get_or_404(user_id)
    # 统计该用户的数据
    article_cnt = Article.query.filter_by(user_id=user.id, is_draft=False).count()
    category_cnt = Category.query.filter_by(user_id=user.id).count()
    tag_cnt = Tag.query.filter_by(user_id=user.id).count()
    # 只查询该用户“已发布”的文章，不能让别人看到草稿
    articles = Article.query.filter_by(user_id=user.id, is_draft=False).order_by(Article.update_time.desc()).all()

    return render_template('user_profile.html',
                           target_user=user,
                           articles=articles,
                           article_count=article_cnt,
                           category_count=category_cnt,
                           tag_count=tag_cnt)


# --- 编辑文章 ---
@app.route('/article/edit/<int:article_id>', methods=['GET', 'POST'])
@login_required
def edit_article(article_id):
    article = Article.query.filter_by(id=article_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        article.title = request.form.get('title')
        article.summary = request.form.get('summary')
        article.content = request.form.get('content')

        # 1. 处理分类
        category_name = request.form.get('category', '').strip()
        if not category_name:
            article.category_id = None
        else:
            category = Category.query.filter_by(name=category_name, user_id=current_user.id).first()
            if not category:
                category = Category(name=category_name, user_id=current_user.id)
                db.session.add(category)
                db.session.commit()
            article.category_id = category.id

        # 2. 处理封面更新 (如果有新上传的文件)
        cover_file = request.files.get('cover_file')
        if cover_file and cover_file.filename != '':
            cover_path = save_article_cover(cover_file, article.id)
            article.cover_url = cover_path

        # 3. 更新标签
        raw_tags = request.form.get('tags', '')
        tag_names = raw_tags.replace('，', ',').split(',')
        article.tags = []
        for name in tag_names:
            name = name.strip()
            if not name: continue
            tag = Tag.query.filter_by(name=name, user_id=current_user.id).first()
            if not tag:
                tag = Tag(name=name, user_id=current_user.id)
                db.session.add(tag)
                db.session.commit()
            article.tags.append(tag)

        article.is_draft = (request.form.get('post_status') == 'draft')
        db.session.commit()
        flash('文章更新成功！')
        return redirect(url_for('dashboard'))

    user_categories = Category.query.filter_by(user_id=current_user.id).all()
    tag_str = ",".join([t.name for t in article.tags])
    return render_template('edit_article.html', article=article, categories=user_categories, tag_str=tag_str)


def save_article_cover(file, article_id):
    if file and file.filename != '':
        # 1. 确定存储路径: static/uploads/users/<user_id>/covers/
        # 假设你之前已经定义了 get_user_upload_path 辅助函数
        upload_path = get_user_upload_path(current_user.id, 'covers')

        # 2. 获取文件后缀名 (例如 .jpg, .png)
        ext = os.path.splitext(file.filename)[1]

        # 3. 构造文件名：文章ID + 后缀
        filename = f"{article_id}{ext}"
        full_path = os.path.join(upload_path, filename)

        # 4. 保存文件
        file.save(full_path)

        # 5. 返回数据库存储的相对路径
        return f"/static/uploads/users/{current_user.id}/covers/{filename}"
    return None


# 文章详细页面
@app.route('/article/<int:article_id>')
def view_article(article_id):
    # 获取文章，如果不存在或未发布（草稿）则返回 404
    # 注意：这里可以根据需要决定是否允许未登录用户看
    article = Article.query.get_or_404(article_id)

    # 如果是草稿，且当前用户不是作者，则不许看
    if article.is_draft and (not current_user.is_authenticated or current_user.id != article.user_id):
        flash("该文章尚未发布")
        return redirect(url_for('index'))

    return render_template('article_detail.html', article=article)


@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    current_user.nickname = request.form.get('nickname')
    current_user.gender = request.form.get('gender')
    current_user.repo_link = request.form.get('repo_link')
    current_user.bio = request.form.get('bio')

    db.session.commit()
    flash('个人资料更新成功！', 'success')
    return redirect(url_for('dashboard'))


@app.route('/user/<int:user_id>/category/<int:cat_id>')
def category_filter(user_id, cat_id):
    user = User.query.get_or_404(user_id)
    category = Category.query.get_or_404(cat_id)
    # 筛选该用户、该分类下已发布的文章
    articles = Article.query.filter_by(user_id=user_id, category_id=cat_id, is_draft=False).order_by(
        Article.update_time.desc()).all()
    return render_template('filter_results.html', user=user, filter_name=category.name, articles=articles, type='分类')


# --- 标签筛选页 ---
@app.route('/user/<int:user_id>/tag/<int:tag_id>')
def tag_filter(user_id, tag_id):
    user = User.query.get_or_404(user_id)
    tag = Tag.query.get_or_404(tag_id)
    # 多对多查询：通过标签找文章
    articles = tag.articles.filter_by(user_id=user_id, is_draft=False).order_by(Article.update_time.desc()).all()
    return render_template('filter_results.html', user=user, filter_name=tag.name, articles=articles, type='标签')


# --- 词云/聚合页 ---
@app.route('/user/<int:user_id>/archive')
def user_archive(user_id):
    user = User.query.get_or_404(user_id)

    # 准备分类数据及其文章数
    categories_data = []
    for cat in user.categories:
        count = Article.query.filter_by(category_id=cat.id, is_draft=False).count()
        if count > 0:
            categories_data.append({'id': cat.id, 'name': cat.name, 'count': count})

    # 准备标签数据及其文章数
    tags_data = []
    for tag in user.tags:
        count = tag.articles.filter_by(is_draft=False).count()
        if count > 0:
            tags_data.append({'id': tag.id, 'name': tag.name, 'count': count})

    return render_template('user_cloud.html', user=user, categories=categories_data, tags=tags_data)


@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'article')  # 默认搜文章
    results = []

    if query:
        if search_type == 'article':
            # 模糊搜索已发布的文章标题
            results = Article.query.filter(
                Article.title.contains(query),
                Article.is_draft == False
            ).order_by(Article.update_time.desc()).all()
        elif search_type == 'user':
            # 模糊搜索用户昵称或账号
            results = User.query.filter(
                db.or_(
                    User.nickname.contains(query),
                    User.username.contains(query)
                )
            ).all()

    return render_template('search.html', query=query, search_type=search_type, results=results)


@app.route('/api/summarize/<int:article_id>')
def ai_summarize(article_id):
    article = Article.query.get_or_404(article_id)

    # 构造发送给 AI 的提示词
    prompt = f"请简要总结这篇文章的核心内容，字数控制在150字左右，使用亲和、专业的语气：\n标题：{article.title}\n正文：{article.content[:2000]}"  # 限制长度防止超限

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的博客助手，擅长提炼文章摘要。"},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post(DEEPSEEK_BASE_URL, json=data, headers=headers, timeout=30)
        res_data = response.json()
        summary = res_data['choices'][0]['message']['content']
        return {"success": True, "summary": summary}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.route('/article/<int:article_id>/comment', methods=['POST'])
@login_required
def post_comment(article_id):
    content = request.form.get('content')
    if not content or content.strip() == "":
        flash("评论内容不能为空", "error")
        return redirect(url_for('view_article', article_id=article_id))

    new_comment = Comment(
        content=content,
        user_id=current_user.id,
        article_id=article_id
    )
    db.session.add(new_comment)
    db.session.commit()
    flash("评论发表成功！", "success")
    return redirect(url_for('view_article', article_id=article_id))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # 创建数据库文件
    app.run(debug=True)
