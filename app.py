from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask.views import MethodView
from models import db, User, Article, Category, Tag, Comment
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
import os
import requests
import re
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- 配置区 ---
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'uploads', 'users')
DEEPSEEK_API_KEY = "sk-9217291767384ccbaceeb57bc804a710"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/chat/completions"

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- 辅助工具函数 ---
def get_user_upload_path(user_id, folder_name):
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id), folder_name)
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


# ======================================================
# 1. OOP 基类设计 (核心思想：封装与复用)
# ======================================================

class BaseView(MethodView):
    """所有视图的父类"""

    def render(self, template, **context):
        return render_template(template, **context)


class ArticleBaseView(BaseView):
    """文章处理基类：封装了繁琐的分类、标签解析逻辑"""

    def handle_article_logic(self, article):
        article.title = request.form.get('title') or "未命名草稿"
        article.summary = request.form.get('summary')
        article.content = request.form.get('content')
        article.is_draft = (request.form.get('post_status') == 'draft')

        # 分类处理 (私有)
        cat_name = request.form.get('category', '').strip()
        if cat_name:
            cat = Category.query.filter_by(name=cat_name, user_id=current_user.id).first()
            if not cat:
                cat = Category(name=cat_name, user_id=current_user.id)
                db.session.add(cat)
                db.session.commit()
            article.category_id = cat.id
        else:
            article.category_id = None

        # 标签处理 (多对多关联)
        tag_names = request.form.get('tags', '').replace('，', ',').split(',')
        article.tags = []
        for name in tag_names:
            name = name.strip()
            if name:
                tag = Tag.query.filter_by(name=name, user_id=current_user.id).first()
                if not tag:
                    tag = Tag(name=name, user_id=current_user.id)
                    db.session.add(tag)
                    db.session.commit()
                article.tags.append(tag)

    def save_cover_img(self, article_id):
        """保存裁剪后的封面"""
        file = request.files.get('cover_file')
        if file and file.filename != '':
            upload_path = get_user_upload_path(current_user.id, 'covers')
            ext = os.path.splitext(file.filename)[1]
            filename = f"{article_id}{ext}"
            file.save(os.path.join(upload_path, filename))
            return f"/static/uploads/users/{current_user.id}/covers/{filename}"
        return None


# ======================================================
# 2. 身份验证类视图 (Login & Register)
# ======================================================

class LoginView(BaseView):
    def get(self):
        if current_user.is_authenticated: return redirect(url_for('index'))
        return self.render('login.html')

    def post(self):
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            user.last_login = datetime.now()
            db.session.commit()
            flash("欢迎回来！", 'success')
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误', 'error')
        return self.render('login.html')


class RegisterView(BaseView):
    def get(self):
        return self.render('register.html')

    def post(self):
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('该用户名已被占用', 'error')
            return self.render('register.html')

        hashed = generate_password_hash(password)
        new_user = User(username=username, password=hashed)
        db.session.add(new_user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))


# ======================================================
# 3. 文章核心类视图 (Create & Edit)
# ======================================================

class CreateArticleView(ArticleBaseView):
    decorators = [login_required]

    def get(self):
        cats = Category.query.filter_by(user_id=current_user.id).all()
        return self.render('write_article.html', categories=cats)

    def post(self):
        new_art = Article(user_id=current_user.id, title="", content="")
        self.handle_article_logic(new_art)
        db.session.add(new_art)
        db.session.flush()  # 获取自增 ID

        cover = self.save_cover_img(new_art.id)
        if cover: new_art.cover_url = cover

        db.session.commit()
        flash('已保存', 'success')
        return redirect(url_for('dashboard'))


class EditArticleView(ArticleBaseView):
    decorators = [login_required]

    def get(self, article_id):
        art = Article.query.filter_by(id=article_id, user_id=current_user.id).first_or_404()
        cats = Category.query.filter_by(user_id=current_user.id).all()
        tag_str = ",".join([t.name for t in art.tags])
        return self.render('edit_article.html', article=art, categories=cats, tag_str=tag_str)

    def post(self, article_id):
        art = Article.query.filter_by(id=article_id, user_id=current_user.id).first_or_404()
        self.handle_article_logic(art)
        cover = self.save_cover_img(art.id)
        if cover: art.cover_url = cover
        db.session.commit()
        flash('更新成功', 'success')
        return redirect(url_for('dashboard'))


# ======================================================
# 4. 筛选与搜索类视图 (体现多态与 Overriding)
# ======================================================

class BaseFilterView(BaseView):
    def fetch_data(self, user_id, **kwargs): raise NotImplementedError

    def get(self, user_id, **kwargs):
        user = User.query.get_or_404(user_id)
        articles, name, label = self.fetch_data(user_id, **kwargs)
        return self.render('filter_results.html', user=user, articles=articles, filter_name=name, type=label)


class CategoryFilterView(BaseFilterView):
    def fetch_data(self, user_id, cat_id):
        cat = Category.query.get_or_404(cat_id)
        arts = Article.query.filter_by(user_id=user_id, category_id=cat_id, is_draft=False).all()
        return arts, cat.name, '分类'


class TagFilterView(BaseFilterView):
    def fetch_data(self, user_id, tag_id):
        tag = Tag.query.get_or_404(tag_id)
        arts = tag.articles.filter_by(user_id=user_id, is_draft=False).all()
        return arts, tag.name, '标签'


class SearchView(BaseView):
    def get(self):
        q, t = request.args.get('q', '').strip(), request.args.get('type', 'article')
        res = []
        if q:
            if t == 'article':
                res = Article.query.filter(Article.title.contains(q), Article.is_draft == False).all()
            else:
                res = User.query.filter(db.or_(User.nickname.contains(q), User.username.contains(q))).all()
        return self.render('search.html', query=q, search_type=t, results=res)


# ======================================================
# 5. 其他功能类视图 (AI总结 & 评论)
# ======================================================

class AISummarizeView(MethodView):
    def get(self, article_id):
        art = Article.query.get_or_404(article_id)
        prompt = f"请总结文章核心内容：\n标题：{art.title}\n正文：{art.content[:1500]}"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "stream": False}
        try:
            r = requests.post(DEEPSEEK_BASE_URL, json=payload, headers=headers, timeout=30).json()
            return jsonify({"success": True, "summary": r['choices'][0]['message']['content']})
        except Exception as e:
            return jsonify({"success": False, "message": "AI 暂时离线"})


class CommentView(MethodView):
    decorators = [login_required]

    def post(self, article_id):
        content = request.form.get('content', '').strip()
        if content:
            db.session.add(Comment(content=content, user_id=current_user.id, article_id=article_id))
            db.session.commit()
            flash("评论发表成功", 'success')
        return redirect(url_for('view_article', article_id=article_id))


# ======================================================
# 6. 普通函数路由 (首页、面板、删除)
# ======================================================

@app.route('/')
def index():
    arts = Article.query.filter_by(is_draft=False).order_by(Article.update_time.desc()).all()
    return render_template('index.html', articles=arts)


@app.route('/dashboard')
@login_required
def dashboard():
    arts = Article.query.filter_by(user_id=current_user.id).order_by(Article.update_time.desc()).all()
    return render_template('dashboard.html', articles=arts, article_count=len(arts),
                           category_count=Category.query.filter_by(user_id=current_user.id).count(),
                           tag_count=Tag.query.filter_by(user_id=current_user.id).count())


@app.route('/article/<int:article_id>')
def view_article(article_id):
    art = Article.query.get_or_404(article_id)
    if art.is_draft and (not current_user.is_authenticated or current_user.id != art.user_id):
        return redirect(url_for('index'))
    return render_template('article_detail.html', article=art)


@app.route('/user/<int:user_id>')
def public_profile(user_id):
    u = User.query.get_or_404(user_id)
    arts = Article.query.filter_by(user_id=user_id, is_draft=False).all()
    return render_template('user_profile.html', target_user=u, articles=arts, article_count=len(arts),
                           category_count=Category.query.filter_by(user_id=user_id).count(),
                           tag_count=Tag.query.filter_by(user_id=user_id).count())


@app.route('/user/<int:user_id>/archive')
def user_archive(user_id):
    u = User.query.get_or_404(user_id)
    cats = [{'id': c.id, 'name': c.name, 'count': Article.query.filter_by(category_id=c.id, is_draft=False).count()} for
            c in u.categories]
    tags = [{'id': t.id, 'name': t.name, 'count': t.articles.filter_by(is_draft=False).count()} for t in u.tags]
    return render_template('user_cloud.html', user=u, categories=cats, tags=tags)


@app.route('/article/delete/<int:article_id>')
@login_required
def delete_article(article_id):
    art = Article.query.filter_by(id=article_id, user_id=current_user.id).first_or_404()
    db.session.delete(art);
    db.session.commit()
    flash("文章已删除", "success")
    return redirect(url_for('dashboard'))


@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    current_user.nickname = request.form.get('nickname')
    current_user.gender = request.form.get('gender')
    current_user.repo_link = request.form.get('repo_link')
    current_user.bio = request.form.get('bio')
    db.session.commit();
    flash('资料已更新', 'success')
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('login'))


# --- 图片上传 ---
@app.route('/upload_article_img', methods=['POST'])
@login_required
def upload_article_img():
    file = request.files.get('editormd-image-file')
    if not file: return jsonify({'success': 0, 'message': '无文件'})
    path = get_user_upload_path(current_user.id, 'articles')
    name = secure_filename(file.filename)
    file.save(os.path.join(path, name))
    return jsonify({'success': 1, 'url': f'/static/uploads/users/{current_user.id}/articles/{name}'})


@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar_file')
    if file:
        path = get_user_upload_path(current_user.id, 'avatar')
        name = "avatar_" + secure_filename(file.filename)
        file.save(os.path.join(path, name))
        current_user.avatar_url = f'/static/uploads/users/{current_user.id}/avatar/{name}'
        db.session.commit()
    return "OK", 200


# ======================================================
# 7. 类视图路由注册 (注册点)
# ======================================================
app.add_url_rule('/login', view_func=LoginView.as_view('login'))
app.add_url_rule('/register', view_func=RegisterView.as_view('register'))
app.add_url_rule('/article/new', view_func=CreateArticleView.as_view('create_article'))
app.add_url_rule('/article/edit/<int:article_id>', view_func=EditArticleView.as_view('edit_article'))
app.add_url_rule('/search', view_func=SearchView.as_view('search'))
app.add_url_rule('/api/summarize/<int:article_id>', view_func=AISummarizeView.as_view('ai_summarize'))
app.add_url_rule('/article/<int:article_id>/comment', view_func=CommentView.as_view('post_comment'))
app.add_url_rule('/user/<int:user_id>/category/<int:cat_id>', view_func=CategoryFilterView.as_view('category_filter'))
app.add_url_rule('/user/<int:user_id>/tag/<int:tag_id>', view_func=TagFilterView.as_view('tag_filter'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)