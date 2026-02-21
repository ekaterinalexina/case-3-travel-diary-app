"""
Дневник путешествий — веб-приложение на Flask + SQLite.

Позволяет пользователям создавать записи о путешествиях с геопозицией,
стоимостью и оценками, а также просматривать записи других пользователей.
"""

import os
import sqlite3
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, flash, g, abort
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Конфигурация приложения
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['DATABASE'] = os.path.join(app.root_path, 'travel_diary.db')

# ---------------------------------------------------------------------------
# Flask-Login
# ---------------------------------------------------------------------------

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице.'
login_manager.login_message_category = 'warning'


class User(UserMixin):
    """Модель пользователя для Flask-Login."""

    def __init__(self, id, username, email, password_hash, created_at):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.created_at = created_at


@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя по идентификатору для Flask-Login."""
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if row:
        return User(**row)
    return None


# ---------------------------------------------------------------------------
# Работа с базой данных
# ---------------------------------------------------------------------------

def get_db():
    """Получение соединения с базой данных (сохраняется в контексте запроса)."""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Закрытие соединения с базой данных после завершения запроса."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Инициализация базы данных: создание таблиц."""
    db = get_db()

    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            country TEXT NOT NULL,
            city TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            date_start DATE,
            date_end DATE,
            total_cost REAL,
            currency TEXT DEFAULT 'RUB',
            rating_convenience INTEGER DEFAULT 0,
            rating_safety INTEGER DEFAULT 0,
            rating_nature INTEGER DEFAULT 0,
            visibility TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')

    db.commit()


def seed_db():
    """Заполнение базы данных демонстрационными данными."""
    db = get_db()

    # Проверяем, есть ли уже данные
    count = db.execute('SELECT COUNT(*) FROM trips').fetchone()[0]
    if count > 0:
        return

    # Создаём демо-пользователя
    demo_hash = generate_password_hash('demo123')
    db.execute(
        'INSERT OR IGNORE INTO users (username, email, password_hash) VALUES (?, ?, ?)',
        ('demo', 'demo@example.com', demo_hash)
    )

    traveler_hash = generate_password_hash('travel123')
    db.execute(
        'INSERT OR IGNORE INTO users (username, email, password_hash) VALUES (?, ?, ?)',
        ('traveler', 'traveler@example.com', traveler_hash)
    )

    db.commit()

    demo_user = db.execute('SELECT id FROM users WHERE username = ?', ('demo',)).fetchone()
    traveler_user = db.execute('SELECT id FROM users WHERE username = ?', ('traveler',)).fetchone()

    if not demo_user or not traveler_user:
        return

    demo_id = demo_user['id']
    traveler_id = traveler_user['id']

    # Демонстрационные путешествия с реальными координатами
    sample_trips = [
        (demo_id, 'Красная площадь и Кремль', 'Удивительная прогулка по историческому центру Москвы. '
         'Посетили Кремль, Красную площадь, ГУМ и храм Василия Блаженного. '
         'Незабываемые впечатления от ночной подсветки.',
         'Россия', 'Москва', 55.7558, 37.6173,
         '2024-06-10', '2024-06-15', 45000, 'RUB', 5, 4, 3, 'public'),

        (demo_id, 'Романтический Париж', 'Неделя в городе любви! Эйфелева башня, Лувр, '
         'Монмартр, круиз по Сене. Потрясающая французская кухня и уютные кафе.',
         'Франция', 'Париж', 48.8566, 2.3522,
         '2024-04-01', '2024-04-08', 2500, 'EUR', 4, 4, 4, 'public'),

        (traveler_id, 'Токио: будущее и традиции', 'Невероятный контраст древних храмов и '
         'ультрасовременных технологий. Акихабара, Синдзюку, Асакуса — каждый район как отдельный мир.',
         'Япония', 'Токио', 35.6762, 139.6503,
         '2024-03-15', '2024-03-25', 3200, 'USD', 5, 5, 4, 'public'),

        (traveler_id, 'Вечный город Рим', 'Колизей, Пантеон, Фонтан Треви, Ватикан — '
         'каждый шаг здесь пропитан тысячелетней историей. Итальянская кухня выше всяких похвал.',
         'Италия', 'Рим', 41.9028, 12.4964,
         '2024-07-20', '2024-07-27', 1800, 'EUR', 4, 3, 4, 'public'),

        (demo_id, 'Стамбул — мост между мирами', 'Город на двух континентах поражает '
         'воображение. Голубая мечеть, Айя-София, Гранд-Базар, '
         'прогулки по Босфору — всё это оставляет незабываемые впечатления.',
         'Турция', 'Стамбул', 41.0082, 28.9784,
         '2024-09-05', '2024-09-12', 1200, 'USD', 4, 3, 5, 'public'),

        (traveler_id, 'Солнечная Барселона', 'Архитектура Гауди, пляжи Барселонеты, '
         'бульвар Рамбла, потрясающие тапас и сангрия. '
         'Город, который никогда не спит.',
         'Испания', 'Барселона', 41.3874, 2.1686,
         '2024-08-10', '2024-08-17', 1500, 'EUR', 5, 4, 5, 'public'),

        (demo_id, 'Санкт-Петербург — Северная столица', 'Эрмитаж, Петергоф, белые ночи, '
         'разводные мосты, Невский проспект. Культурная столица России '
         'покоряет своей красотой и величием.',
         'Россия', 'Санкт-Петербург', 59.9343, 30.3351,
         '2024-06-20', '2024-06-27', 55000, 'RUB', 5, 4, 4, 'public'),

        (traveler_id, 'Бангкок — город контрастов', 'Величественные храмы соседствуют с '
         'небоскрёбами, а уличная еда не уступает ресторанной. '
         'Плавучие рынки, тук-туки и невероятное гостеприимство.',
         'Таиланд', 'Бангкок', 13.7563, 100.5018,
         '2024-01-10', '2024-01-20', 1100, 'USD', 4, 3, 4, 'public'),
    ]

    for trip in sample_trips:
        db.execute(
            '''INSERT INTO trips
               (user_id, title, description, country, city, latitude, longitude,
                date_start, date_end, total_cost, currency,
                rating_convenience, rating_safety, rating_nature, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            trip
        )

    db.commit()


# ---------------------------------------------------------------------------
# Вспомогательные функции и фильтры Jinja2
# ---------------------------------------------------------------------------

# Символы валют для отображения
CURRENCY_SYMBOLS = {
    'RUB': '\u20bd',
    'USD': '$',
    'EUR': '\u20ac',
    'GBP': '\u00a3',
    'JPY': '\u00a5',
    'TRY': '\u20ba',
    'THB': '\u0e3f',
}


@app.template_filter('currency_symbol')
def currency_symbol_filter(currency_code):
    """Jinja2-фильтр: код валюты -> символ."""
    return CURRENCY_SYMBOLS.get(currency_code, currency_code)


@app.template_filter('format_date')
def format_date_filter(date_str):
    """Jinja2-фильтр: форматирование даты в удобочитаемый вид."""
    if not date_str:
        return ''
    try:
        dt = datetime.strptime(str(date_str), '%Y-%m-%d')
        return dt.strftime('%d.%m.%Y')
    except (ValueError, TypeError):
        return str(date_str)


@app.template_filter('stars')
def stars_filter(value):
    """Jinja2-фильтр: число -> звёзды (Unicode)."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return ''
    return '\u2605' * n + '\u2606' * (5 - n)


@app.template_filter('avg_rating')
def avg_rating_filter(trip):
    """Jinja2-фильтр: средняя оценка путешествия."""
    ratings = [
        trip['rating_convenience'] or 0,
        trip['rating_safety'] or 0,
        trip['rating_nature'] or 0,
    ]
    valid = [r for r in ratings if r > 0]
    if not valid:
        return 0
    return round(sum(valid) / len(valid), 1)


# ---------------------------------------------------------------------------
# Маршруты: Аутентификация
# ---------------------------------------------------------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Валидация
        errors = []
        if not username or len(username) < 3:
            errors.append('Имя пользователя должно содержать минимум 3 символа.')
        if not email or '@' not in email:
            errors.append('Введите корректный адрес электронной почты.')
        if not password or len(password) < 6:
            errors.append('Пароль должен содержать минимум 6 символов.')
        if password != password_confirm:
            errors.append('Пароли не совпадают.')

        if not errors:
            db = get_db()
            # Проверка уникальности
            existing = db.execute(
                'SELECT id FROM users WHERE username = ? OR email = ?',
                (username, email)
            ).fetchone()

            if existing:
                errors.append('Пользователь с таким именем или email уже существует.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('register.html', username=username, email=email)

        # Создание пользователя
        db = get_db()
        db.execute(
            'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
            (username, email, generate_password_hash(password))
        )
        db.commit()

        flash('Регистрация прошла успешно! Теперь войдите в систему.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        row = db.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()

        if row and check_password_hash(row['password_hash'], password):
            user = User(**row)
            login_user(user)
            flash(f'Добро пожаловать, {user.username}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))

        flash('Неверное имя пользователя или пароль.', 'danger')
        return render_template('login.html', username=username)

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Выход из системы."""
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Маршруты: Путешествия
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Главная страница — все публичные путешествия с фильтрами."""
    db = get_db()

    # Параметры фильтрации
    country_filter = request.args.get('country', '').strip()
    sort_by = request.args.get('sort', 'date_desc')

    # Базовый запрос
    query = '''
        SELECT trips.*, users.username
        FROM trips
        JOIN users ON trips.user_id = users.id
        WHERE trips.visibility = 'public'
    '''
    params = []

    # Фильтр по стране
    if country_filter:
        query += ' AND trips.country = ?'
        params.append(country_filter)

    # Сортировка
    sort_options = {
        'date_desc': 'trips.date_start DESC',
        'date_asc': 'trips.date_start ASC',
        'cost_desc': 'trips.total_cost DESC',
        'cost_asc': 'trips.total_cost ASC',
        'rating_desc': '(COALESCE(trips.rating_convenience, 0) + '
                       'COALESCE(trips.rating_safety, 0) + '
                       'COALESCE(trips.rating_nature, 0)) DESC',
        'created_desc': 'trips.created_at DESC',
    }
    order = sort_options.get(sort_by, 'trips.date_start DESC')
    query += f' ORDER BY {order}'

    trips = db.execute(query, params).fetchall()

    # Список стран для фильтра
    countries = db.execute(
        "SELECT DISTINCT country FROM trips WHERE visibility = 'public' ORDER BY country"
    ).fetchall()

    return render_template(
        'index.html',
        trips=trips,
        countries=countries,
        current_country=country_filter,
        current_sort=sort_by,
    )


@app.route('/trip/new', methods=['GET', 'POST'])
@login_required
def trip_new():
    """Создание новой записи о путешествии."""
    if request.method == 'POST':
        return _save_trip(None)

    return render_template('trip_form.html', trip=None, editing=False)


@app.route('/trip/<int:trip_id>')
def trip_detail(trip_id):
    """Просмотр записи о путешествии с картой."""
    db = get_db()
    trip = db.execute(
        '''SELECT trips.*, users.username
           FROM trips
           JOIN users ON trips.user_id = users.id
           WHERE trips.id = ?''',
        (trip_id,)
    ).fetchone()

    if not trip:
        abort(404)

    # Проверка доступа к приватным записям
    if trip['visibility'] != 'public':
        if not current_user.is_authenticated or current_user.id != trip['user_id']:
            abort(403)

    return render_template('trip_detail.html', trip=trip)


@app.route('/trip/<int:trip_id>/edit', methods=['GET', 'POST'])
@login_required
def trip_edit(trip_id):
    """Редактирование записи о путешествии."""
    db = get_db()
    trip = db.execute('SELECT * FROM trips WHERE id = ?', (trip_id,)).fetchone()

    if not trip:
        abort(404)

    if trip['user_id'] != current_user.id:
        abort(403)

    if request.method == 'POST':
        return _save_trip(trip_id)

    return render_template('trip_form.html', trip=trip, editing=True)


@app.route('/trip/<int:trip_id>/delete', methods=['POST'])
@login_required
def trip_delete(trip_id):
    """Удаление записи о путешествии."""
    db = get_db()
    trip = db.execute('SELECT * FROM trips WHERE id = ?', (trip_id,)).fetchone()

    if not trip:
        abort(404)

    if trip['user_id'] != current_user.id:
        abort(403)

    db.execute('DELETE FROM trips WHERE id = ?', (trip_id,))
    db.commit()

    flash('Запись о путешествии удалена.', 'info')
    return redirect(url_for('my_trips'))


@app.route('/my-trips')
@login_required
def my_trips():
    """Страница с записями текущего пользователя."""
    db = get_db()
    trips = db.execute(
        '''SELECT * FROM trips
           WHERE user_id = ?
           ORDER BY created_at DESC''',
        (current_user.id,)
    ).fetchall()

    return render_template('my_trips.html', trips=trips)


@app.route('/user/<username>')
def user_profile(username):
    """Профиль пользователя с его публичными путешествиями."""
    db = get_db()
    user = db.execute(
        'SELECT * FROM users WHERE username = ?', (username,)
    ).fetchone()

    if not user:
        abort(404)

    trips = db.execute(
        '''SELECT * FROM trips
           WHERE user_id = ? AND visibility = 'public'
           ORDER BY date_start DESC''',
        (user['id'],)
    ).fetchall()

    return render_template('profile.html', profile_user=user, trips=trips)


# ---------------------------------------------------------------------------
# Вспомогательная функция сохранения путешествия
# ---------------------------------------------------------------------------

def _save_trip(trip_id):
    """Сохранение (создание или обновление) записи о путешествии."""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    country = request.form.get('country', '').strip()
    city = request.form.get('city', '').strip()
    date_start = request.form.get('date_start', '').strip()
    date_end = request.form.get('date_end', '').strip()
    visibility = request.form.get('visibility', 'public')

    # Геопозиция
    lat_str = request.form.get('latitude', '').strip()
    lng_str = request.form.get('longitude', '').strip()
    latitude = float(lat_str) if lat_str else None
    longitude = float(lng_str) if lng_str else None

    # Стоимость
    cost_str = request.form.get('total_cost', '').strip()
    total_cost = float(cost_str) if cost_str else None
    currency = request.form.get('currency', 'RUB')

    # Оценки
    def parse_rating(field):
        val = request.form.get(field, '0')
        try:
            r = int(val)
            return max(0, min(5, r))
        except (ValueError, TypeError):
            return 0

    rating_convenience = parse_rating('rating_convenience')
    rating_safety = parse_rating('rating_safety')
    rating_nature = parse_rating('rating_nature')

    # Валидация
    errors = []
    if not title:
        errors.append('Укажите название путешествия.')
    if not country:
        errors.append('Укажите страну.')
    if not city:
        errors.append('Укажите город.')

    if errors:
        for err in errors:
            flash(err, 'danger')
        if trip_id:
            return redirect(url_for('trip_edit', trip_id=trip_id))
        return render_template('trip_form.html', trip=request.form, editing=(trip_id is not None))

    db = get_db()

    if trip_id:
        # Обновление существующей записи
        db.execute(
            '''UPDATE trips SET
                title = ?, description = ?, country = ?, city = ?,
                latitude = ?, longitude = ?,
                date_start = ?, date_end = ?,
                total_cost = ?, currency = ?,
                rating_convenience = ?, rating_safety = ?, rating_nature = ?,
                visibility = ?
               WHERE id = ? AND user_id = ?''',
            (title, description, country, city,
             latitude, longitude,
             date_start or None, date_end or None,
             total_cost, currency,
             rating_convenience, rating_safety, rating_nature,
             visibility,
             trip_id, current_user.id)
        )
        db.commit()
        flash('Запись обновлена!', 'success')
        return redirect(url_for('trip_detail', trip_id=trip_id))
    else:
        # Создание новой записи
        cursor = db.execute(
            '''INSERT INTO trips
               (user_id, title, description, country, city,
                latitude, longitude,
                date_start, date_end,
                total_cost, currency,
                rating_convenience, rating_safety, rating_nature,
                visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (current_user.id, title, description, country, city,
             latitude, longitude,
             date_start or None, date_end or None,
             total_cost, currency,
             rating_convenience, rating_safety, rating_nature,
             visibility)
        )
        db.commit()
        flash('Новая запись о путешествии создана!', 'success')
        return redirect(url_for('trip_detail', trip_id=cursor.lastrowid))


# ---------------------------------------------------------------------------
# Обработка ошибок
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    """Обработчик ошибки 404 — страница не найдена."""
    flash('Страница не найдена.', 'warning')
    return redirect(url_for('index'))


@app.errorhandler(403)
def forbidden(e):
    """Обработчик ошибки 403 — доступ запрещён."""
    flash('У вас нет доступа к этой странице.', 'danger')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Инициализация и запуск
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()
    seed_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
