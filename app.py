from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, time
import re
from flask_socketio import SocketIO
from flask_migrate import Migrate
import json

import pytz

local_tz = pytz.timezone("Europe/Berlin")  # Укажите временную зону ресторана
now = datetime.now(local_tz)
current_time = now.time()


app = Flask(__name__)
app.secret_key = 'simple_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)
socketio = SocketIO(app)

# Модель клиента
class Kunde(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vorname = db.Column(db.String(120), nullable=False)
    nachname = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    adresse = db.Column(db.String(255), nullable=False)
    postleitzahl = db.Column(db.String(20), nullable=False)
    passwort = db.Column(db.String(120), nullable=False)


# Модель ресторана
class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    adresse = db.Column(db.String(255), nullable=False)
    postleitzahl = db.Column(db.String(20), nullable=False)
    beschreibung = db.Column(db.String(255), nullable=True)
    passwort = db.Column(db.String(120), nullable=False)

    # Новое поле для рабочего времени
    arbeitstage = db.Column(db.String(255), nullable=False)  # Для хранения дней работы (Mo-Su)
    oeffnungszeiten = db.Column(db.String(255), nullable=False)  # Для хранения времени (например: "09:00-22:00")

# Модель меню
class Speisekarte(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(120), nullable=False)
    beschreibung = db.Column(db.String(255), nullable=True)
    preis = db.Column(db.Float, nullable=False)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'), nullable=False)

    restaurant = db.relationship('Restaurant', backref=db.backref('speisekarte', lazy=True))

class Bestellung(db.Model):
    __tablename__ = 'bestellung'

    id = db.Column(db.Integer, primary_key=True)  # Уникальный ID заказа
    kunde_id = db.Column(db.Integer, db.ForeignKey('kunde.id'), nullable=False)  # ID клиента, оформившего заказ
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'), nullable=False)  # ID ресторана
    inhalt = db.Column(db.Text, nullable=False)  # Содержимое заказа в формате JSON
    bemerkungen = db.Column(db.String(255))  # Уточнения (если есть)
    status = db.Column(db.String(50), default="in Bearbeitung")  # Статус заказа (по умолчанию "В обработке")
    gesamtkosten = db.Column(db.Float, nullable=False)  # Общая стоимость заказа
    erstellt_am = db.Column(db.DateTime, default=datetime.now(timezone.utc)) # Дата создания заказа

    # Связи
    kunde = db.relationship("Kunde", backref="bestellungen", lazy=True)
    restaurant = db.relationship("Restaurant", backref="bestellungen", lazy=True)

@app.route('/')
def main():
    user_email = session.get('user_email')
    is_restaurant = session.get('is_restaurant')

    if user_email:
        if is_restaurant:
            return redirect(url_for('restaurant_menu'))
        else:
            return redirect(url_for('restaurant_list'))
    return render_template('main.html')

@app.route('/registration_users', methods=['GET', 'POST'])
def registration_user():
    if request.method == 'POST':
        # Получение данных формы
        vorname = request.form.get('vorname')
        nachname = request.form.get('nachname')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        postleitzahl = request.form.get('postleitzahl')
        passwort = request.form.get('passwort')

        # Создание нового пользователя
        new_user = Kunde(
            vorname=vorname,
            nachname=nachname,
            email=email,
            adresse=adresse,
            postleitzahl=postleitzahl,
            passwort=passwort
        )
        db.session.add(new_user)
        db.session.commit()

        # Сохраняем ID пользователя в сессию
        session['user_email'] = email
        session['user_id'] = new_user.id  # <-- Сохраняем ID
        session['is_restaurant'] = False  # Пользователь - не ресторан
        return redirect(url_for('main'))
    return render_template("register_users.html")

@app.route('/registration_restaurants', methods=['GET', 'POST'])
def registration_restaurants():
    if request.method == 'POST':
        # Получение данных из формы
        name = request.form.get('name')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        postleitzahl = request.form.get('postleitzahl')
        beschreibung = request.form.get('beschreibung')
        passwort = request.form.get('passwort')
        arbeitstage = request.form.get('arbeitstage')
        oeffnungszeiten = request.form.get('oeffnungszeiten')

        # Валидация uniqueness email
        existing_restaurant = Restaurant.query.filter_by(email=email).first()
        if existing_restaurant:
            flash('Ein Restaurant mit dieser Email existiert bereits.', 'error')
            return redirect(request.url)

        # Валидация arbeitstage (дни работы)
        weekday_pattern = r'^(?:Mo|Di|Mi|Do|Fr|Sa|So)(?:-(?:Mo|Di|Mi|Do|Fr|Sa|So))?$'
        for part in arbeitstage.split(', '):
            if not re.match(weekday_pattern, part):
                flash("Ungültiges Arbeitstage-Format! Beispiel: Mo-Fr, Sa", "error")
                return redirect(request.url)

        # Валидация oeffnungszeiten (время работы)
        time_pattern = r'^\d{2}:\d{2}-\d{2}:\d{2}$'  # Формат HH:MM-HH:MM
        if not re.match(time_pattern, oeffnungszeiten):
            flash("Ungültiges Zeitformat! Beispiel: 09:00-22:00", "error")
            return redirect(request.url)

        # Создание и добавление нового ресторана
        new_restaurant = Restaurant(
            name=name,
            email=email,
            adresse=adresse,
            postleitzahl=postleitzahl,
            beschreibung=beschreibung,
            passwort=passwort,
            arbeitstage=arbeitstage,
            oeffnungszeiten=oeffnungszeiten
        )
        db.session.add(new_restaurant)
        db.session.commit()

        # Установка сессии
        session['user_email'] = email
        session['is_restaurant'] = True
        return redirect(url_for('main'))

    # Если GET-запрос, отобразить форму
    return render_template("register_restaurants.html")

@app.route('/profile')
def profile():
    # Проверяем, авторизован ли пользователь
    user_email = session.get('user_email')
    if not user_email:
        return redirect(url_for('login'))

    # Проверяем роль: Клиент или Ресторан
    if session.get('is_restaurant'):
        # Если ресторан, загружаем данные ресторана
        restaurant = Restaurant.query.filter_by(email=user_email).first()
        if not restaurant:
            return redirect(url_for('login'))  # На случай удаления ресторана из базы
        return render_template('profile_restaurant.html', restaurant=restaurant)
    else:
        # Если клиент, загружаем данные клиента
        entity = Kunde.query.filter_by(email=user_email).first()
        if not entity:
            return redirect(url_for('login'))  # На случай удаления пользователя из базы
        return render_template('profile.html', entity=entity)

@app.route('/restaurant_menu', methods=['GET', 'POST'])
def restaurant_menu():
    # Überprüfen, ob der Benutzer ein Restaurant ist
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    # Das aktuelle Restaurant basierend auf der E-Mail in der Session abrufen
    restaurant_email = session.get('user_email')
    restaurant = Restaurant.query.filter_by(email=restaurant_email).first()

    # Wenn kein Restaurant gefunden wurde, zurück zur Login-Seite leiten
    if not restaurant:
        return redirect(url_for('login'))

    # POST-Request: Neuer Menüpunkt wird hinzugefügt
    if request.method == 'POST':
        try:
            # Formulardaten abrufen
            item = request.form.get('item')  # Name des Gerichts
            beschreibung = request.form.get('beschreibung')  # Beschreibung
            preis = request.form.get('preis')  # Preis (€)

            # Neuen Menüpunkt erstellen und speichern
            new_menu_item = Speisekarte(
                item=item,
                beschreibung=beschreibung,
                preis=float(preis),
                restaurant_id=restaurant.id
            )
            db.session.add(new_menu_item)
            db.session.commit()

            flash('Menüpunkt erfolgreich hinzugefügt!', 'success')  # Erfolgsbenachrichtigung
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Hinzufügen des Menüpunkts: {str(e)}', 'danger')

    # Alle Menüpunkte des aktuellen Restaurants abrufen
    menu_items = Speisekarte.query.filter_by(restaurant_id=restaurant.id).all()

    # Template mit restaurant und menu_items rendern
    return render_template('restaurant_menu.html', menu_items=menu_items, restaurant=restaurant)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Получение данных из формы
        email = request.form.get('email')
        passwort = request.form.get('passwort')

        # 1. Попытка найти пользователя среди клиентов
        user = Kunde.query.filter_by(email=email, passwort=passwort).first()
        is_restaurant = False

        # 2. Если клиент не найден, ищем среди ресторанов
        if not user:
            user = Restaurant.query.filter_by(email=email, passwort=passwort).first()
            is_restaurant = True

        # 3. Если найден либо клиент, либо ресторан
        if user:
            session['user_email'] = email
            session['user_id'] = user.id
            session['is_restaurant'] = is_restaurant
            print(f"Login successful: {email}, restaurant: {is_restaurant}")
            return redirect(url_for('main'))

        # 4. Если пользователь не найден
        flash('Ungültige Anmeldedaten. Bitte überprüfen Sie Ihre E-Mail und Passwort.', 'error')
        return redirect(url_for('login'))

    # При GET-запросе просто отображаем страницу логина
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_id', None)  # <-- Удаляем user_id из сессии
    session.pop('is_restaurant', None)
    return redirect(url_for('main'))

@app.route('/restaurants', methods=['GET'])
def restaurant_list():
    # Получение списка всех ресторанов
    restaurants = Restaurant.query.all()

    open_restaurants = []

    for restaurant in restaurants:
        is_open = is_restaurant_open(restaurant.arbeitstage, restaurant.oeffnungszeiten)
        print(
            f"DEBUG: Restaurant {restaurant.name} is_open={is_open} arbeitstage={restaurant.arbeitstage} oeffnungszeiten={restaurant.oeffnungszeiten}")
        if is_open:
            open_restaurants.append(restaurant)

    return render_template('restaurant_list.html', restaurants=open_restaurants)

def is_restaurant_open(arbeitstage, oeffnungszeiten):
    """
    Проверяет, открыт ли ресторан в данный момент.
    """
    # Сопоставление дней недели с индексом Python
    weekday_map = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    now = datetime.now(timezone.utc)  # Используем текущее UTC-время
    current_day = weekday_map[now.weekday()]  # Определяем текущий день недели (например, "Mo")
    current_time = now.time()  # Текущее время

    # Парсим дни работы ресторана
    parsed_days = parse_arbeitstage(arbeitstage)  # ['Mo', 'Di', 'Fr', ...]

    # Если текущий день не входит в диапазон работы, сразу возвращаем False
    if current_day not in parsed_days:
        return False

    # Парсим время работы ресторана
    open_time_str, close_time_str = oeffnungszeiten.split("-")
    open_time = datetime.strptime(open_time_str.strip(), "%H:%M").time()
    close_time = datetime.strptime(close_time_str.strip(), "%H:%M").time()

    # Проверяем диапазон времени
    if open_time <= close_time:
        # Если время работы находится в рамках одного дня
        print(f"DEBUG: Single day check: {open_time} <= {current_time} <= {close_time}")
        return open_time <= current_time <= close_time
    else:
        # Исправленная логика для времени, захватывающего полночь
        print(f"DEBUG: Overnight check: {current_time} >= {open_time} or {current_time} <= {close_time}")
        if close_time == time(0, 0):  # Обработка случая "00:30-00:00"
            close_time_extended = time(23, 59, 59)  # Считаем полночь как конец текущего дня (24:00)
            return open_time <= current_time or current_time <= close_time_extended
        return current_time >= open_time or current_time <= close_time

@app.route('/update_profile_restaurant', methods=['POST'])
def update_profile_restaurant():
    user_email = session.get('user_email')
    if not session.get('is_restaurant') or not user_email:
        return redirect(url_for('login'))

    # Получение данных из формы
    name = request.form.get('name')
    email = request.form.get('email')
    adresse = request.form.get('adresse')
    postleitzahl = request.form.get('postleitzahl')
    beschreibung = request.form.get('beschreibung')
    arbeitstage = request.form.get('arbeitstage')
    oeffnungszeiten = request.form.get('oeffnungszeiten')

    # Валидация введенных данных
    weekday_pattern = r'^(?:Mo|Di|Mi|Do|Fr|Sa|So)(?:-(?:Mo|Di|Mi|Do|Fr|Sa|So))?$'
    time_pattern = r'^\d{2}:\d{2}-\d{2}:\d{2}$'

    for part in arbeitstage.split(', '):
        if not re.match(weekday_pattern, part):
            flash("Ungültiges Arbeitstage-Format! Beispiel: Mo-Fr, Sa", "error")
            return redirect(request.url)

    if not re.match(time_pattern, oeffnungszeiten):
        flash("Ungültiges Zeitformat! Beispiel: 09:00-22:00", "error")
        return redirect(request.url)

    # Поиск ресторана
    restaurant = Restaurant.query.filter_by(email=user_email).first()
    if not restaurant:
        flash('Restaurant nicht gefunden.', 'error')
        return redirect(url_for('profile'))

    # Обновление данных
    restaurant.name = name
    restaurant.email = email
    restaurant.adresse = adresse
    restaurant.postleitzahl = postleitzahl
    restaurant.beschreibung = beschreibung
    restaurant.arbeitstage = arbeitstage
    restaurant.oeffnungszeiten = oeffnungszeiten

    # Сохранение изменений
    db.session.commit()

    flash('Ihre Daten wurden erfolgreich aktualisiert.', 'success')
    return redirect(url_for('profile'))

def parse_arbeitstage(arbeitstage):
    weekday_map = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    days = set()

    parts = arbeitstage.split(", ")
    for part in parts:
        if "-" in part:  # Диапазон, например: Mo-Fr
            start, end = part.split("-")
            start_index = weekday_map.index(start)
            end_index = weekday_map.index(end) + 1
            days.update(weekday_map[start_index:end_index])
        else:  # Один день, например: Sa
            days.add(part)

    return list(days)  # Пример вывода: ['Mo', 'Di', 'Mi', 'Do', 'Fr']

def parse_oeffnungszeiten(oeffnungszeiten):
    start, end = oeffnungszeiten.split("-")
    return {"start": start, "end": end}

@app.route('/menu/<int:restaurant_id>', methods=['GET'])
def menu_view(restaurant_id):
    restaurant = Restaurant.query.get_or_404(restaurant_id)
    menu_items = Speisekarte.query.filter_by(restaurant_id=restaurant.id).all()

    # Вытаскиваем корзину из сессии
    cart = session.get('cart', [])

    # Считаем общую сумму товаров в корзине (total_price)
    total_price = sum(item['price'] * item['quantity'] for item in cart if 'price' in item)

    # Сохраняем ID текущего ресторана в сессии, чтобы вернуться назад при клике
    session['last_visited_restaurant_id'] = restaurant_id

    # Передаём в шаблон данные о ресторане, меню и общей цене
    return render_template(
        "menu_view.html",
        restaurant=restaurant,
        menu_items=menu_items,
        total_price=total_price  # Передаём уже посчитанную общую стоимость
    )

@app.route('/edit_menu_item/<int:item_id>', methods=['POST'])
def edit_menu_item(item_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    menu_item = Speisekarte.query.get_or_404(item_id)
    menu_item.item = request.form.get('item')
    menu_item.beschreibung = request.form.get('beschreibung')

    # Обновляем цену
    try:
        menu_item.preis = float(request.form.get('preis'))
        db.session.commit()  # Сохраняем изменения в базе
        flash('Preis wurde erfolgreich aktualisiert.', 'success')
    except ValueError:
        flash('Ungültiger Wert für Preis.', 'error')

    return redirect(url_for('restaurant_menu'))

@app.route('/delete_menu_item/<int:item_id>', methods=['POST'])
def delete_menu_item(item_id):
    """
    Функция для удаления пунктов меню.
    """
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))  # Перенаправление к логину, если пользователь не авторизован.

    # Поиск элемента меню по ID. Если не найден, вернуть 404 ошибку.
    menu_item = Speisekarte.query.get_or_404(item_id)

    # Удаление элемента из базы данных.
    db.session.delete(menu_item)
    db.session.commit()

    flash('Menüpunkt wurde erfolgreich gelöscht.', 'success')  # Сообщение об успешном удалении.
    return redirect(url_for('restaurant_menu'))  # Перенаправление обратно на страницу меню.

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    item_id = int(request.form['item_id'])
    quantity = int(request.form['quantity'])

    menu_item = Speisekarte.query.get(item_id)
    if not menu_item:
        return jsonify({'error': 'Item not found'}), 404

    cart = session.get('cart', [])
    item_exists_in_cart = False

    for item in cart:
        if item['id'] == menu_item.id:
            item['quantity'] += quantity
            item_exists_in_cart = True
            break

    if not item_exists_in_cart:
        cart.append(
            {'id': menu_item.id, 'name': menu_item.item, 'quantity': quantity, 'price': menu_item.preis}
        )
    session['cart'] = cart

    # Формируем данные корзины для ответа
    cart_items = [
        {
            'id': item['id'],
            'name': item['name'],
            'quantity': item['quantity'],
            'price': item['price'],
            'total_price': item['price'] * item['quantity']
        }
        for item in cart
    ]
    total_price = sum(item['price'] * item['quantity'] for item in cart)

    return jsonify({
        'cart_items': cart_items,
        'total_price': total_price
    })

@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    cart = session.get('cart', [])
    item_id = int(request.form['item_id'])
    quantity = max(1, int(request.form['quantity']))

    for item in cart:
        if item["id"] == item_id:
            item["quantity"] = quantity
            item["total_price"] = item["price"] * item["quantity"]

    session["cart"] = cart
    total_price = sum(item["total_price"] for item in cart)
    return jsonify({
        "cart_items": cart,
        "item_total": next(item["total_price"] for item in cart if item["id"] == item_id),
        "total_price": total_price
    })

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    cart = session.get('cart', [])
    item_id = int(request.form['item_id'])
    cart = [item for item in cart if item["id"] != item_id]
    session["cart"] = cart
    total_price = sum(item["price"] * item["quantity"] for item in cart)
    return jsonify({
        "cart_items": cart,
        "total_price": total_price
    })

@app.template_filter('fromjson')
def fromjson(value):
    """Конвертирует строку JSON в Python-объект."""
    import json
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = session.get('cart', [])
    total_price = sum(item['price'] * item['quantity'] for item in cart)

    return render_template('checkout.html', cart_items=cart, total_price=total_price)

@app.route('/process_checkout', methods=['POST'])
def process_checkout():
    try:
        kunde_id = session.get('user_id')
        if not kunde_id:
            flash("Sie müssen sich anmelden, um Ihre Bestellung abzuschließen.", "error")
            return redirect(url_for('login'))

        restaurant_id = session.get('last_visited_restaurant_id')
        if not restaurant_id:
            flash("Restaurant wurde nicht gefunden. Bitte erneut versuchen.", "error")
            return redirect(url_for('main'))

        # Получаем товары из корзины (из сессии)
        cart = session.get('cart', [])
        if not cart:
            flash("Ihr Warenkorb ist leer. Bitte fügen Sie Artikel hinzu, bevor Sie eine Bestellung aufgeben.", "error")
            return redirect(url_for('menu_view', restaurant_id=restaurant_id))

        # Примечания клиента
        bemerkungen = request.form.get('bemerkungen', '')

        # Рассчитать общую стоимость заказа
        total_price = 0.0
        for item in cart:
            menu_item = Speisekarte.query.get(item['id'])
            if menu_item:  # Используем цену на момент заказа
                item['price'] = menu_item.preis
                total_price += item['quantity'] * menu_item.preis

        # Сохраняем заказ в базу данных
        new_order = Bestellung(
            kunde_id=kunde_id,
            restaurant_id=restaurant_id,
            inhalt=json.dumps(cart),  # Сохраняем состав заказа
            bemerkungen=bemerkungen,
            gesamtkosten=total_price,  # Поля total_price
            erstellt_am=datetime.now(timezone.utc)
        )
        db.session.add(new_order)
        db.session.commit()

        # Очищаем корзину
        session.pop('cart', None)

        return redirect(url_for('order_confirmation', order_id=new_order.id))

    except Exception as e:
        db.session.rollback()
        flash(f"Fehler bei der Bestellung: {e}", "error")
        return redirect(url_for('checkout'))

@app.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    # Получаем заказ
    order = Bestellung.query.get_or_404(order_id)

    # Преобразуем строку JSON из поля `inhalt` в Python-объект
    try:
        order_content = json.loads(order.inhalt)
    except (TypeError, ValueError) as e:
        return f"Ошибка обработки JSON: {e}", 400

    # Отправляем готовый Python-объект в шаблон
    return render_template('order_confirmation.html', order=order, order_content=order_content)

@app.route('/order_history')
def order_history():
    kunde_id = session.get('user_id')
    if not kunde_id:
        flash("Bitte melden Sie sich an, um Ihre Bestellungen zu sehen.", "error")
        return redirect(url_for('login'))

    # Активные заказы: те, что только находятся "в обработке" или "готовятся" (приняты)
    orders_active = Bestellung.query.filter(
        Bestellung.kunde_id == kunde_id,
        Bestellung.status.in_(['in Bearbeitung', 'angenommen'])  # Только эти статусы
    ).order_by(Bestellung.erstellt_am.desc()).all()

    # Завершенные: отклоненные или уже выполненные
    orders_completed = Bestellung.query.filter(
        Bestellung.kunde_id == kunde_id,
        Bestellung.status.in_(['abgeschlossen', 'abgelehnt'])
    ).order_by(Bestellung.erstellt_am.desc()).all()

    return render_template('order_history.html', orders_active=orders_active, orders_completed=orders_completed)

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    # Получаем заказ
    order = Bestellung.query.get_or_404(order_id)

    # Убедимся, что заказ принадлежит текущему ресторану
    restaurant_id = session.get('user_id')
    if order.restaurant_id != restaurant_id:
        flash("Вы не можете изменять этот заказ.", "error")
        return redirect(url_for('order_history_restaurant'))

    # Получаем новый статус
    new_status = request.form.get('status')
    valid_status_transitions = {
        "in Bearbeitung": ["angenommen", "abgelehnt"],  # В обработке → принято/отклонено
        "angenommen": ["abgeschlossen"],  # Принято → завершено
        "abgelehnt": [],  # Отклонено — больше изменений невозможно
        "abgeschlossen": []  # Завершено — больше изменений невозможно
    }

    if new_status not in valid_status_transitions[order.status]:
        flash(f"Недопустимый переход статусов: {order.status} → {new_status}.", "error")
        return redirect(url_for('order_history_restaurant'))

    # Логируем для дебага
    print(f"[DEBUG] Изменение статуса заказа #{order.id}: {order.status} → {new_status}")

    # Обновляем статус
    order.status = new_status
    db.session.commit()

    flash(f"Статус заказа #{order.id} успешно обновлён на '{new_status}'.", 'success')
    return redirect(url_for('order_history_restaurant'))

@app.route('/order_history_restaurant')
def order_history_restaurant():
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    restaurant_id = session.get('user_id')

    # Активные заказы: только в обработке или активно готовятся
    orders_active = Bestellung.query.filter(
        Bestellung.restaurant_id == restaurant_id,
        Bestellung.status.in_(['in Bearbeitung', 'angenommen'])  # Только активные статусы
    ).order_by(Bestellung.erstellt_am.desc()).all()

    # Завершенные или отклоненные заказы
    orders_completed = Bestellung.query.filter(
        Bestellung.restaurant_id == restaurant_id,
        Bestellung.status.in_(['abgeschlossen', 'abgelehnt'])  # Завершенные статусы
    ).order_by(Bestellung.erstellt_am.desc()).all()

    return render_template(
        'order_history_restaurant.html',
        orders_active=orders_active,
        orders_completed=orders_completed
    )

@app.route('/order_details/<int:order_id>')
def order_details(order_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    order = Bestellung.query.get_or_404(order_id)  # Получаем заказ
    restaurant_id = session.get('user_id')

    # Проверяем, принадлежит ли заказ текущему ресторану
    if order.restaurant_id != restaurant_id:
        flash("Sie haben keine Berechtigung für diesen Auftrag.", "error")
        return redirect(url_for('order_history_restaurant'))

    return render_template('order_details.html', order=order)

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)  # Удаляем корзину из сессии
    flash('Ihr Warenkorb wurde geleert.', 'success')
    return redirect(request.referrer or url_for('checkout'))

@app.route('/clear_database', methods=['GET', 'POST'])
def clear_database_route():
    """Очищает базу данных через HTTP-запрос (теперь доступно для GET и POST)."""
    try:
        db.session.query(Speisekarte).delete()
        db.session.query(Restaurant).delete()
        db.session.query(Kunde).delete()

        db.session.commit()
        return jsonify({'message': "База данных успешно очищена!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f"Ошибка при очистке базы данных: {str(e)}"}), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Создание таблиц
    app.run(debug=True)
