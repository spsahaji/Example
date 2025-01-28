from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, time
import re
from flask_socketio import SocketIO
from flask_migrate import Migrate
import json
import pytz
from sqlalchemy.orm import scoped_session, sessionmaker

local_tz = pytz.timezone("Europe/Berlin")
now = datetime.now(local_tz)
current_time = now.time()


app = Flask(__name__)
app.secret_key = 'simple_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db?check_same_thread=False'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True

db = SQLAlchemy(app)

with app.app_context():
    db_session = scoped_session(sessionmaker(bind=db.engine))

migrate = Migrate(app, db)
socketio = SocketIO(app)

class Kunde(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vorname = db.Column(db.String(120), nullable=False)
    nachname = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    adresse = db.Column(db.String(255), nullable=False)
    postleitzahl = db.Column(db.String(20), nullable=False)
    passwort = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, default=100.0)  # Новый клиентский баланс


class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    adresse = db.Column(db.String(255), nullable=False)
    postleitzahl = db.Column(db.String(20), nullable=False)
    beschreibung = db.Column(db.String(255), nullable=True)
    passwort = db.Column(db.String(120), nullable=False)
    arbeitstage = db.Column(db.String(255), nullable=False)
    oeffnungszeiten = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Float, default=0.0)  # Баланс ресторана


# Глобальный баланс для платформы Lieferspatz
lieferspatz_balance = 0.0

class PlattformGuthaben(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    balance = db.Column(db.Float, nullable=False, default=0.0)

class Speisekarte(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(120), nullable=False)
    beschreibung = db.Column(db.String(255), nullable=True)
    preis = db.Column(db.Float, nullable=False)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'), nullable=False)

    restaurant = db.relationship('Restaurant', backref=db.backref('speisekarte', lazy=True))

class Bestellung(db.Model):
    __tablename__ = 'bestellung'

    id = db.Column(db.Integer, primary_key=True)
    kunde_id = db.Column(db.Integer, db.ForeignKey('kunde.id'), nullable=False)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'), nullable=False)
    inhalt = db.Column(db.Text, nullable=False)
    bemerkungen = db.Column(db.String(255))  # Уточнения (если есть)
    status = db.Column(db.String(50), default="in Bearbeitung")
    gesamtkosten = db.Column(db.Float, nullable=False)
    erstellt_am = db.Column(db.DateTime, default=datetime.now(timezone.utc))

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
        vorname = request.form.get('vorname')
        nachname = request.form.get('nachname')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        postleitzahl = request.form.get('postleitzahl')
        passwort = request.form.get('passwort')

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

        session['user_email'] = email
        session['user_id'] = new_user.id
        session['is_restaurant'] = False
        return redirect(url_for('main'))
    return render_template("register_users.html")

@app.route('/registration_restaurants', methods=['GET', 'POST'])
def registration_restaurants():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        postleitzahl = request.form.get('postleitzahl')
        beschreibung = request.form.get('beschreibung')
        passwort = request.form.get('passwort')
        arbeitstage = request.form.get('arbeitstage')
        oeffnungszeiten = request.form.get('oeffnungszeiten')

        existing_restaurant = Restaurant.query.filter_by(email=email).first()
        if existing_restaurant:
            flash('Ein Restaurant mit dieser Email existiert bereits.', 'error')
            return redirect(request.url)

        weekday_pattern = r'^(?:Mo|Di|Mi|Do|Fr|Sa|So)(?:-(?:Mo|Di|Mi|Do|Fr|Sa|So))?$'
        for part in arbeitstage.split(', '):
            if not re.match(weekday_pattern, part):
                flash("Ungültiges Arbeitstage-Format! Beispiel: Mo-Fr, Sa", "error")
                return redirect(request.url)

        time_pattern = r'^\d{2}:\d{2}-\d{2}:\d{2}$'
        if not re.match(time_pattern, oeffnungszeiten):
            flash("Ungültiges Zeitformat! Beispiel: 09:00-22:00", "error")
            return redirect(request.url)

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

        session['user_email'] = email
        session['is_restaurant'] = True
        return redirect(url_for('main'))

    return render_template("register_restaurants.html")

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user_email = session.get('user_email')
    is_restaurant = session.get('is_restaurant')

    if not user_email:
        return redirect(url_for('login'))

    if is_restaurant:
        entity = Restaurant.query.filter_by(email=user_email).first()
    else:
        entity = Kunde.query.filter_by(email=user_email).first()

    if not entity:
        flash("Benutzer nicht gefunden. Bitte melden Sie sich erneut an.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        entity.vorname = request.form.get('vorname')
        entity.nachname = request.form.get('nachname')
        entity.email = request.form.get('email')
        entity.adresse = request.form.get('adresse')
        entity.postleitzahl = request.form.get('postleitzahl')

        try:
            db.session.commit()
            flash("Profil erfolgreich aktualisiert.", "success")
        except Exception as e:
            db.session.rollback()
            flash("Ein Fehler ist aufgetreten. Bitte erneut versuchen.", "error")

    return render_template('profile.html', entity=entity)

@app.route('/restaurant_menu', methods=['GET', 'POST'])
def restaurant_menu():
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    restaurant_email = session.get('user_email')
    restaurant = Restaurant.query.filter_by(email=restaurant_email).first()

    if not restaurant:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            item = request.form.get('item')
            beschreibung = request.form.get('beschreibung')
            preis = request.form.get('preis')

            print(f"DEBUG: POST-Daten -> item: {item}, beschreibung: {beschreibung}, preis: {preis}")

            if not item or not preis:
                flash("Das Gericht benötigt mindestens einen Namen und einen gültigen Preis.", 'danger')
                return redirect(url_for('restaurant_menu'))

            try:
                preis = float(preis)
            except ValueError:
                flash("Ungültiges Format für Preis. Bitte geben Sie eine Zahl ein.", "danger")
                return redirect(url_for("restaurant_menu"))

            if not restaurant or not restaurant.id:
                flash("Restaurant nicht gefunden. Bitte melden Sie sich erneut an.", "danger")
                return redirect(url_for('login'))

            print(f"DEBUG: Restaurant ID = {restaurant.id}")

            new_menu_item = Speisekarte(
                item=item,
                beschreibung=beschreibung,
                preis=preis,
                restaurant_id=restaurant.id
            )

            db.session.add(new_menu_item)
            db.session.commit()

            flash('Menüpunkt erfolgreich hinzugefügt!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: Fehler beim Hinzufügen: {str(e)}")
            flash(f'Fehler beim Hinzufügen des Menüpunkts: {str(e)}', 'danger')

    menu_items = Speisekarte.query.filter_by(restaurant_id=restaurant.id).all()

    return render_template('restaurant_menu.html', menu_items=menu_items, restaurant=restaurant)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        passwort = request.form.get('passwort')

        user = Kunde.query.filter_by(email=email, passwort=passwort).first()
        is_restaurant = False

        if not user:
            user = Restaurant.query.filter_by(email=email, passwort=passwort).first()
            is_restaurant = True

        if user:
            session['user_email'] = email
            session['user_id'] = user.id
            session['is_restaurant'] = is_restaurant
            print(f"Login successful: {email}, restaurant: {is_restaurant}")
            return redirect(url_for('main'))

        flash('Ungültige Anmeldedaten. Bitte überprüfen Sie Ihre E-Mail und Passwort.', 'error')
        return redirect(url_for('login'))

    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_id', None)
    session.pop('is_restaurant', None)
    return redirect(url_for('main'))

@app.route('/restaurants', methods=['GET'])
def restaurant_list():
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
    weekday_map = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    now = datetime.now(timezone.utc)
    current_day = weekday_map[now.weekday()]
    current_time = now.time()

    parsed_days = parse_arbeitstage(arbeitstage)

    if current_day not in parsed_days:
        return False

    open_time_str, close_time_str = oeffnungszeiten.split("-")
    open_time = datetime.strptime(open_time_str.strip(), "%H:%M").time()
    close_time = datetime.strptime(close_time_str.strip(), "%H:%M").time()

    if open_time <= close_time:
        print(f"DEBUG: Single day check: {open_time} <= {current_time} <= {close_time}")
        return open_time <= current_time <= close_time
    else:
        print(f"DEBUG: Overnight check: {current_time} >= {open_time} or {current_time} <= {close_time}")
        if close_time == time(0, 0):
            close_time_extended = time(23, 59, 59)
            return open_time <= current_time or current_time <= close_time_extended
        return current_time >= open_time or current_time <= close_time

@app.route('/update_profile_restaurant', methods=['POST'])
def update_profile_restaurant():
    user_email = session.get('user_email')
    if not session.get('is_restaurant') or not user_email:
        return redirect(url_for('login'))

    name = request.form.get('name')
    email = request.form.get('email')
    adresse = request.form.get('adresse')
    postleitzahl = request.form.get('postleitzahl')
    beschreibung = request.form.get('beschreibung')
    arbeitstage = request.form.get('arbeitstage')
    oeffnungszeiten = request.form.get('oeffnungszeiten')

    weekday_pattern = r'^(?:Mo|Di|Mi|Do|Fr|Sa|So)(?:-(?:Mo|Di|Mi|Do|Fr|Sa|So))?$'
    time_pattern = r'^\d{2}:\d{2}-\d{2}:\d{2}$'

    for part in arbeitstage.split(', '):
        if not re.match(weekday_pattern, part):
            flash("Ungültiges Arbeitstage-Format! Beispiel: Mo-Fr, Sa", "error")
            return redirect(request.url)

    if not re.match(time_pattern, oeffnungszeiten):
        flash("Ungültiges Zeitformat! Beispiel: 09:00-22:00", "error")
        return redirect(request.url)

    restaurant = Restaurant.query.filter_by(email=user_email).first()
    if not restaurant:
        flash('Restaurant nicht gefunden.', 'error')
        return redirect(url_for('profile'))

    restaurant.name = name
    restaurant.email = email
    restaurant.adresse = adresse
    restaurant.postleitzahl = postleitzahl
    restaurant.beschreibung = beschreibung
    restaurant.arbeitstage = arbeitstage
    restaurant.oeffnungszeiten = oeffnungszeiten

    db.session.commit()

    flash('Ihre Daten wurden erfolgreich aktualisiert.', 'success')
    return redirect(url_for('profile'))

def parse_arbeitstage(arbeitstage):
    weekday_map = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    days = set()

    parts = arbeitstage.split(", ")
    for part in parts:
        if "-" in part:
            start, end = part.split("-")
            start_index = weekday_map.index(start)
            end_index = weekday_map.index(end) + 1
            days.update(weekday_map[start_index:end_index])
        else:
            days.add(part)

    return list(days)

def parse_oeffnungszeiten(oeffnungszeiten):
    start, end = oeffnungszeiten.split("-")
    return {"start": start, "end": end}

@app.route('/menu/<int:restaurant_id>', methods=['GET'])
def menu_view(restaurant_id):
    restaurant = Restaurant.query.get_or_404(restaurant_id)
    menu_items = Speisekarte.query.filter_by(restaurant_id=restaurant.id).all()

    cart = session.get('cart', [])

    total_price = sum(item['price'] * item['quantity'] for item in cart if 'price' in item)

    session['last_visited_restaurant_id'] = restaurant_id

    return render_template(
        "menu_view.html",
        restaurant=restaurant,
        menu_items=menu_items,
        total_price=total_price
    )

@app.route('/edit_menu_item/<int:item_id>', methods=['POST'])
def edit_menu_item(item_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    menu_item = Speisekarte.query.get_or_404(item_id)
    menu_item.item = request.form.get('item')
    menu_item.beschreibung = request.form.get('beschreibung')

    try:
        menu_item.preis = float(request.form.get('preis'))
        db.session.commit()
        flash('Preis wurde erfolgreich aktualisiert.', 'success')
    except ValueError:
        flash('Ungültiger Wert für Preis.', 'error')

    return redirect(url_for('restaurant_menu'))

@app.route('/delete_menu_item/<int:item_id>', methods=['POST'])
def delete_menu_item(item_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    menu_item = Speisekarte.query.get_or_404(item_id)

    db.session.delete(menu_item)
    db.session.commit()

    flash('Menüpunkt wurde erfolgreich gelöscht.', 'success')
    return redirect(url_for('restaurant_menu'))

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
        # Проверяем, залогинен ли пользователь
        kunde_id = session.get('user_id')
        if not kunde_id:
            flash("Sie müssen sich anmelden, um Ihre Bestellung abzuschließen.", "error")
            return redirect(url_for('login'))

        # Проверяем, выбрано ли ресторанное меню
        restaurant_id = session.get('last_visited_restaurant_id')
        if not restaurant_id:
            flash("Restaurant wurde nicht gefunden. Bitte erneut versuchen.", "error")
            return redirect(url_for('main'))

        # Проверяем, не пустая ли корзина
        cart = session.get('cart', [])
        if not cart:
            flash("Ihr Warenkorb ist leer. Bitte fügen Sie Artikel hinzu, bevor Sie eine Bestellung aufgeben.", "error")
            return redirect(url_for('menu_view', restaurant_id=restaurant_id))

        bemerkungen = request.form.get('bemerkungen', '')

        # Подготовка данных для корзины и расчет общей суммы заказа
        total_price = 0.0
        cart_snapshot = []

        for item in cart:
            menu_item = Speisekarte.query.get(item['id'])
            if menu_item:
                cart_item = {
                    'item_id': menu_item.id,
                    'name': menu_item.item,
                    'beschreibung': menu_item.beschreibung,
                    'price_at_order': menu_item.preis,
                    'quantity': item['quantity']
                }
                cart_snapshot.append(cart_item)
                total_price += item['quantity'] * menu_item.preis

       # Проверяем баланс клиента
        customer = Kunde.query.get(kunde_id)
        if customer.balance < total_price:
            flash("Nicht genügend Guthaben für diese Bestellung.", "error")
            return redirect(url_for('checkout'))

        # Снимаем деньги с баланса клиента (но только временно, до успешного завершения заказа)
        customer.balance -= total_price

        # Получаем ресторан
        restaurant = Restaurant.query.get(restaurant_id)

        # Обновление баланса ресторанов на основе успешного расчета комиссии
        lieferspatz_cut = round(total_price * 0.15, 2)  # Комиссия Lieferspatz (15%)
        restaurant_earnings = round(total_price * 0.85, 2)  # Доход ресторана (85%)

        restaurant.balance += restaurant_earnings  # Увеличиваем баланс ресторана

        plattform_guthaben = PlattformGuthaben.query.first()
        if not plattform_guthaben:
            # Если запись для платформы отсутствует, создаем её
            plattform_guthaben = PlattformGuthaben(balance=0.0)
            db.session.add(plattform_guthaben)

        # Увеличиваем баланс платформы
        plattform_guthaben.balance += lieferspatz_cut

        # Создаем заказ
        new_order = Bestellung(
            kunde_id=kunde_id,
            restaurant_id=restaurant_id,
            inhalt=json.dumps(cart_snapshot),
            bemerkungen=bemerkungen,
            gesamtkosten=total_price,
            erstellt_am=datetime.now(timezone.utc)
        )
        db.session.add(new_order)
        db.session.commit()  # Успешная транзакция, сохраняем изменения

        # Очистка корзины
        session.pop('cart', None)

        # Учет баланса Lieferspatz
        global lieferspatz_balance
        lieferspatz_balance += lieferspatz_cut

        # Обновляем сессионный баланс клиента
        session['balance'] = round(customer.balance, 2)

        # Переходим на страницу подтверждения заказа
        return redirect(url_for('order_confirmation', order_id=new_order.id))

    except Exception as e:
        # При возникновении ошибки откатываем транзакцию
        db.session.rollback()

        # Возвращаем баланс клиента, если он был уменьшен
        customer = Kunde.query.get(kunde_id)
        if customer and 'total_price' in locals():
            customer.balance += total_price
            db.session.commit()

        # Сообщаем об ошибке
        flash(f"Fehler bei der Bestellung: {e}", "error")
        return redirect(url_for('checkout'))

@app.context_processor
def inject_balance():
    user_email = session.get('user_email')
    if user_email:
        # Если ресторан
        if session.get('is_restaurant'):
            restaurant = Restaurant.query.filter_by(email=user_email).first()
            if restaurant:
                return {'balance': round(restaurant.balance, 2)}
        # Если клиент
        else:
            customer = Kunde.query.filter_by(email=user_email).first()
            if customer:
                return {'balance': round(customer.balance, 2)}
    # Если пользователь не авторизован или баланс не доступен
    return {'balance': None}

@app.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    order = db.session.query(Bestellung).filter_by(id=order_id).first()

    if order is None:
        return "Order not found", 404

    order_content = json.loads(order.inhalt)

    print("order_content:", order_content)

    return render_template('order_confirmation.html', order=order, order_content=order_content)

@app.route('/order_history')
def order_history():
    kunde_id = session.get('user_id')
    if not kunde_id:
        flash("Bitte melden Sie sich an, um Ihre Bestellungen zu sehen.", "error")
        return redirect(url_for('login'))

    orders_active = Bestellung.query.filter(
        Bestellung.kunde_id == kunde_id,
        Bestellung.status.in_(['in Bearbeitung', 'angenommen'])
    ).order_by(Bestellung.erstellt_am.desc()).all()

    orders_completed = Bestellung.query.filter(
        Bestellung.kunde_id == kunde_id,
        Bestellung.status.in_(['abgeschlossen', 'abgelehnt'])
    ).order_by(Bestellung.erstellt_am.desc()).all()

    return render_template('order_history.html', orders_active=orders_active, orders_completed=orders_completed)

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    order = Bestellung.query.get_or_404(order_id)

    restaurant_id = session.get('user_id')
    if order.restaurant_id != restaurant_id:
        flash("Вы не можете изменять этот заказ.", "error")
        return redirect(url_for('order_history_restaurant'))

    new_status = request.form.get('status')

    valid_status_transitions = {
        "in Bearbeitung": ["in Zubereitung", "storniert"],
        "in Zubereitung": ["abgeschlossen", "storniert"],
        "storniert": [],
        "abgeschlossen": []
    }

    if new_status not in valid_status_transitions.get(order.status, []):
        flash(f"Недопустимый переход статуса: {order.status} → {new_status}.", "error")
        return redirect(url_for('order_history_restaurant'))
    order.status = new_status
    db.session.commit()

    flash(f"Статус заказа #{order.id} успешно обновлен на '{new_status}'.", "success")
    return redirect(url_for('order_history_restaurant'))

@app.route('/order_history_restaurant')
def order_history_restaurant():
    if not session.get('is_restaurant'):
        return redirect(url_for('login'))

    restaurant_id = session.get('user_id')

    orders_active = Bestellung.query.filter(
        Bestellung.restaurant_id == restaurant_id,
        Bestellung.status.in_(['in Bearbeitung', 'in Zubereitung'])
    ).order_by(Bestellung.erstellt_am.desc()).all()

    orders_completed = Bestellung.query.filter(
        Bestellung.restaurant_id == restaurant_id,
        Bestellung.status.in_(['abgeschlossen', 'storniert'])
    ).order_by(Bestellung.erstellt_am.desc()).all()

    return render_template(
        'order_history_restaurant.html',
        orders_active=orders_active,
        orders_completed=orders_completed
    )

@app.route('/order_details/<int:order_id>')
def order_details(order_id):
    if not session.get('is_restaurant') and not session.get('user_email'):
        return redirect(url_for('login'))

    order = Bestellung.query.get_or_404(order_id)

    try:
        order_content = json.loads(order.inhalt)

        for item in order_content:
            if 'name' not in item or 'price_at_order' not in item:
                item['name'] = "Unbekanntes Gericht"
                item['price_at_order'] = 0.0
            item['quantity'] = item.get('quantity', 0)

    except (TypeError, ValueError) as e:
        flash(f"Fehler beim Verarbeiten der Bestelldetails: {e}", "error")
        return redirect(url_for('order_history_restaurant'))

    total_cost = sum(item['price_at_order'] * item['quantity'] for item in order_content)

    return render_template(
        'order_details.html',
        order=order,
        order_content=order_content,
        total_cost=total_cost
    )

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    flash('Ihr Warenkorb wurde geleert.', 'success')
    return redirect(request.referrer or url_for('checkout'))

@app.route('/lieferspatz_balance')
def lieferspatz_balance_view():
    plattform_guthaben = PlattformGuthaben.query.first()
    if not plattform_guthaben:
        return "Plattform-Guthaben nicht gefunden.", 404

    return f"Der aktuelle Plattform-Guthaben beträgt: {plattform_guthaben.balance:.2f} €"

if __name__ == '__main__':
    with app.app_context():
        if not PlattformGuthaben.query.first():
            db.session.add(PlattformGuthaben(balance=0.0))
            db.session.commit()
        db.create_all()
    app.run(debug=True)
    app.run(threaded=False)

