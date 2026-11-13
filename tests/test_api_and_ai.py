"""
lafi-api/tests/test_api_and_ai.py
---------------------------------
Suite de tests automatisés pour la soutenance « Développeur Data IA » (Blocs 2, 3, 4 et 5).
Exécutable directement sans dépendance externe :
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import io
import unittest
from PIL import Image
from fastapi import HTTPException, UploadFile
from sqlmodel import Session, SQLModel, create_engine

from app.agent import (
    filter_precise_recommendations,
    generate_product_description,
    run_agent,
    run_local_agent,
)
from app.category_model import load_model as load_text_model
from app.category_model import predict_category
from app.image_model import enhance_image, predict_image
from app.image_model import load_model as load_image_model
from app.models import (
    Article,
    Customer,
    CustomerCreate,
    CustomerLogin,
    CustomerUpdate,
    ForgotPasswordRequest,
    OrderCreate,
    OrderItemIn,
    OtpSend,
    OtpVerify,
    ResetPasswordRequest,
    SendEmailCodeRequest,
    Shop,
    ShopUpdate,
    StatusUpdate,
    ValidatePickup,
    VerifyEmailCodeRequest,
)
from app.routers.articles import list_articles, update_my_shop
from app.routers.auth import (
    check_otp,
    forgot_password,
    login_customer,
    register_customer,
    request_otp,
    reset_password,
    send_email_verification_code,
    update_customer,
    verify_email_code,
    reset_login_attempts,
)
from app.routers.orders import (
    cancel_order,
    create_order,
    dispatch_driver,
    handover_package,
    set_status,
    validate_pickup,
)
from app.seed import seed


class TestLafiApiAndAi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Base de données de test isolée en mémoire vive (ne pollue pas la base réelle lafi.db)
        cls.test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(cls.test_engine)
        with Session(cls.test_engine) as session:
            seed(session, force=True)
        load_text_model()
        load_image_model()

    def test_01_list_articles_and_proximity(self):
        """Bloc 3 : Vérifie que le catalogue retourne les articles ouverts triés par distance Haversine."""
        with Session(self.test_engine) as session:
            items = list_articles(session=session)
            self.assertGreater(len(items), 0)
            distances = [item.distance_m for item in items]
            self.assertEqual(distances, sorted(distances))

    def test_02_server_side_order_price_recalculation(self):
        """Bloc 3 : Vérifie le recalcul serveur des prix et la sécurisation du retrait par code OTP."""
        with Session(self.test_engine) as session:
            items = list_articles(session=session)
            first_article = items[0]
            order_in = OrderCreate(
                mode="yango",
                items=[OrderItemIn(article_id=first_article.id, qty=2)],
                customer_name="Client Test",
                customer_phone="0700000000",
                customer_address="Cocody Riviera",
            )
            order_out = create_order(order_in, session=session)
            expected_subtotal = first_article.price * 2
            self.assertEqual(order_out.subtotal, expected_subtotal)
            self.assertEqual(order_out.total, expected_subtotal + order_out.delivery_fee)

            # Acceptation commerçant puis clôture de la commande Yango
            set_status(order_out.id, StatusUpdate(status="accepted"), x_shop_id=first_article.shop_id, session=session)
            delivered = set_status(order_out.id, StatusUpdate(status="completed"), x_shop_id=first_article.shop_id, session=session)
            self.assertEqual(delivered.status, "completed")

            # Test Retrait en boutique avec code OTP à 4 chiffres
            pickup_in = OrderCreate(
                mode="pickup",
                items=[OrderItemIn(article_id=first_article.id, qty=1)],
                customer_name="Client Retrait",
                customer_phone="0700000001",
            )
            pickup_order = create_order(pickup_in, session=session)
            self.assertEqual(pickup_order.delivery_fee, 0)
            self.assertIsNotNone(pickup_order.pickup_code)
            self.assertEqual(len(pickup_order.pickup_code), 4)

            # Acceptation par le commerçant
            set_status(pickup_order.id, StatusUpdate(status="accepted"), x_shop_id=first_article.shop_id, session=session)

            # Validation du retrait avec le code à 4 chiffres
            validated = validate_pickup(
                pickup_order.id,
                ValidatePickup(code=pickup_order.pickup_code),
                x_shop_id=first_article.shop_id,
                session=session,
            )
            self.assertEqual(validated.status, "completed")

    def test_03_text_classifier_all_six_categories(self):
        """Blocs 2 & 5 : Vérifie que le classifieur de texte couvre les 6 catégories officielles."""
        samples = {
            "Attiéké poisson braisé": "Alimentation",
            "Robe en pagne wax cousue": "Mode",
            "Beurre de karité naturel": "Beauté",
            "Écouteurs sans fil bluetooth": "Électronique",
            "Ventilateur sur pied salon": "Maison",
            "Couches bébé pampers taille 3": "Bébé",
        }
        for title, expected_cat in samples.items():
            res = predict_category(title)
            self.assertIn("source", res)
            self.assertIn("accepte", res)
            self.assertEqual(
                res["category"],
                expected_cat,
                f"Attendu {expected_cat} pour '{title}', obtenu {res['category']}",
            )

    def test_04_image_classifier_and_pillow_enhancer(self):
        """Blocs 2 & 5 : Vérifie l'inférence MobileNetV2 et l'amélioration d'image Pillow."""
        img = Image.new("RGB", (320, 240), color=(185, 133, 74))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        img_bytes = buf.getvalue()

        # 1. Classification MobileNetV2
        pred = predict_image(img_bytes)
        self.assertEqual(pred["source"], "image-model")
        self.assertIn("confiance", pred)
        self.assertEqual(len(pred["propositions"]), 3)

        # 2. Amélioration et recadrage carré par Pillow
        enhanced = enhance_image(img_bytes)
        self.assertTrue(enhanced["accepte"])
        self.assertEqual(enhanced["source"], "pillow-enhancer")
        self.assertTrue(enhanced["url"].startswith("/uploads/enhanced_"))

    def test_05_generate_product_description(self):
        """Blocs 4 & 5 : Vérifie le générateur de description commerciale assisté par IA."""
        res = generate_product_description(
            title="Sac à main en cuir véritable",
            category="Mode",
            price=15000,
            negotiable=True,
        )
        self.assertTrue(res["accepte"])
        self.assertIn(res["source"], ("openrouter", "local-template"))
        self.assertGreater(len(res["description"]), 20)

    def test_06_agent_relevance_and_multiturn_memory(self):
        """Bloc 4 : Vérifie le filtrage anti-hors-sujet et la mémoire conversationnelle multi-tours."""
        with Session(self.test_engine) as session:
            res = run_agent("Je cherche une belle robe", session=session, history=[])
            self.assertIn(res["source"], ("openrouter", "agent-local"))
            for art in res["recommended_articles"]:
                self.assertIn("robe", art.name.lower())

        # Test unitaire déterministe de la mémoire multi-tours sur le moteur de repli local
        shop = Shop(id=1, name="Chez Aïcha", phone="2250700000001", lat=5.36, lng=-3.98, is_open=True)
        articles_data = [
            (Article(id=1, shop_id=1, name="Sac à main en cuir", price=15000, category="Mode"), shop, 340),
            (Article(id=7, shop_id=1, name="Sac malette", price=3000, category="Mode"), shop, 340),
        ]
        local_res = run_local_agent(
            message="Et à moins de 5000 F ?",
            articles_data=articles_data,
            history=[{"role": "user", "content": "Je cherche un sac"}],
        )
        self.assertEqual(local_res["source"], "agent-local")
        self.assertEqual(len(local_res["recommended_articles"]), 1)
        self.assertEqual(local_res["recommended_articles"][0].price, 3000)

    def test_07_otp_soutenance_demo_mode(self):
        """Bloc 3 : Vérifie le mode démonstration OTP (+2250700000000 / code 123456)."""
        send_res = request_otp(OtpSend(phone="+2250700000000"))
        self.assertTrue(send_res.get("test_mode"))
        ver_res = check_otp(OtpVerify(phone="+2250700000000", code="123456"))
        self.assertTrue(ver_res["valid"])

    def test_08_assistant_image_product_search(self):
        """Bloc 4 : Vérifie la recherche de produit par photo dans le catalogue."""
        from app.agent import find_product_from_image
        img_byte_arr = io.BytesIO()
        im = Image.new("RGB", (64, 64), color="blue")
        im.save(img_byte_arr, format="JPEG")
        test_bytes = img_byte_arr.getvalue()

        with Session(self.test_engine) as session:
            res = find_product_from_image(test_bytes, session=session)
            self.assertIn(res["source"], ("openrouter-vision", "agent-local-vision"))
            self.assertIn("recommended_articles", res)
            self.assertGreater(len(res["recommended_articles"]), 0)
            self.assertIn(res["recommended_articles"][0].id, [1, 2])

    def test_09_update_shop_and_customer(self):
        """Bloc 3 : Vérifie la modification des informations de la boutique et du client."""
        with Session(self.test_engine) as session:
            # 1. Mise à jour des informations de la boutique
            updated_shop = update_my_shop(
                ShopUpdate(
                    name="Super Boutique Lafi",
                    address="Cocody Angré 8e Tranche",
                    lat=5.385,
                    lng=-3.992,
                    is_open=True,
                ),
                x_shop_id=1,
                session=session,
            )
            self.assertEqual(updated_shop.name, "Super Boutique Lafi")
            self.assertEqual(updated_shop.address, "Cocody Angré 8e Tranche")
            self.assertEqual(updated_shop.lat, 5.385)
            self.assertEqual(updated_shop.lng, -3.992)

            # 2. Création puis mise à jour d'un client
            c = register_customer(
                CustomerCreate(name="Koffi Test", phone="0701020304", address="Plateau Dokui"),
                session=session,
            )
            self.assertEqual(c.name, "Koffi Test")

            updated_c = update_customer(
                customer_id=c.id,
                data=CustomerUpdate(name="Koffi Modifié", address="Cocody Riviera 2"),
                session=session,
            )
            self.assertEqual(updated_c.name, "Koffi Modifié")
            self.assertEqual(updated_c.address, "Cocody Riviera 2")
            self.assertEqual(updated_c.phone, "0701020304")

    def test_10_yango_driver_dispatch(self):
        """Bloc 3 : Vérifie la confirmation d'envoi du livreur Yango et le cycle de vie de la commande."""
        with Session(self.test_engine) as session:
            # 1. Création d'une commande Yango
            order = create_order(
                OrderCreate(
                    mode="yango",
                    customer_id=1,
                    customer_name="Awa Yango",
                    customer_phone="0709080706",
                    customer_address="Cocody Riviera Palmeraie",
                    items=[OrderItemIn(article_id=1, qty=1)],
                ),
                session=session,
            )
            self.assertEqual(order.mode, "yango")
            self.assertEqual(order.status, "pending")
            self.assertFalse(order.driver_dispatched)

            # 2. Le commerçant accepte la commande
            accepted_order = set_status(
                order_id=order.id,
                data=StatusUpdate(status="accepted"),
                x_shop_id=order.shop_id,
                session=session,
            )
            self.assertEqual(accepted_order.status, "accepted")
            self.assertFalse(accepted_order.driver_dispatched)

            # 3. Le client confirme l'envoi de son livreur Yango
            dispatched_order = dispatch_driver(order_id=order.id, session=session)
            self.assertTrue(dispatched_order.driver_dispatched)
            self.assertFalse(dispatched_order.package_handed_over)

            # 4. Le commerçant marque le colis comme remis au livreur
            handed_order = handover_package(
                order_id=order.id,
                x_shop_id=order.shop_id,
                session=session,
            )
            self.assertTrue(handed_order.package_handed_over)

            # 5. Le commerçant valide la commande une fois le paiement reçu
            completed_order = set_status(
                order_id=order.id,
                data=StatusUpdate(status="completed"),
                x_shop_id=order.shop_id,
                session=session,
            )
            self.assertEqual(completed_order.status, "completed")
            self.assertTrue(completed_order.driver_dispatched)
            self.assertTrue(completed_order.package_handed_over)

    def test_11_order_cancellation(self):
        """Bloc 3 : Vérifie l'annulation client (en attente ou après envoi livreur avant remise colis)."""
        with Session(self.test_engine) as session:
            # 1. Annulation d'une commande en attente (pending)
            o1 = create_order(
                OrderCreate(
                    mode="pickup",
                    customer_id=1,
                    customer_name="Client Test",
                    customer_phone="0709080706",
                    items=[OrderItemIn(article_id=1, qty=1)],
                ),
                session=session,
            )
            self.assertEqual(o1.status, "pending")
            cancelled1 = cancel_order(order_id=o1.id, session=session)
            self.assertEqual(cancelled1.status, "cancelled")

            # 2. Annulation d'une commande acceptée avec livreur envoyé (avant remise colis)
            o2 = create_order(
                OrderCreate(
                    mode="yango",
                    customer_id=1,
                    customer_name="Client Test 2",
                    customer_phone="0709080706",
                    customer_address="Cocody",
                    items=[OrderItemIn(article_id=1, qty=1)],
                ),
                session=session,
            )
            set_status(order_id=o2.id, data=StatusUpdate(status="accepted"), x_shop_id=o2.shop_id, session=session)
            dispatch_driver(order_id=o2.id, session=session)
            cancelled2 = cancel_order(order_id=o2.id, session=session)
            self.assertEqual(cancelled2.status, "cancelled")

            # 3. Impossible d'annuler si le colis a déjà été remis au livreur
            o3 = create_order(
                OrderCreate(
                    mode="yango",
                    customer_id=1,
                    customer_name="Client Test 3",
                    customer_phone="0709080706",
                    customer_address="Cocody",
                    items=[OrderItemIn(article_id=1, qty=1)],
                ),
                session=session,
            )
            set_status(order_id=o3.id, data=StatusUpdate(status="accepted"), x_shop_id=o3.shop_id, session=session)
            dispatch_driver(order_id=o3.id, session=session)
            handover_package(order_id=o3.id, x_shop_id=o3.shop_id, session=session)

            with self.assertRaises(Exception):
                cancel_order(order_id=o3.id, session=session)

    def test_12_email_password_and_forgot_password(self):
        """Bloc 3 : Vérifie l'authentification par email/mot de passe et la réinitialisation de mot de passe."""
        with Session(self.test_engine) as session:
            # 1. Inscription client avec email et mot de passe
            customer = register_customer(
                CustomerCreate(
                    name="Kouassi Test",
                    phone="2250701020304",
                    address="Cocody Angré",
                    email="kouassi@lafi.ci",
                    password="MonSuperPassword123",
                ),
                session=session,
            )
            self.assertEqual(customer.email, "kouassi@lafi.ci")

            # 2. Connexion réussie
            logged = login_customer(
                CustomerLogin(email="kouassi@lafi.ci", password="MonSuperPassword123"),
                session=session,
            )
            self.assertEqual(logged.id, customer.id)

            # 3. Échec de connexion avec mauvais mot de passe
            with self.assertRaises(Exception):
                login_customer(
                    CustomerLogin(email="kouassi@lafi.ci", password="MauvaisPassword"),
                    session=session,
                )

            # 4. Demande de code de réinitialisation (Mot de passe oublié)
            forgot_res = forgot_password(
                ForgotPasswordRequest(email="kouassi@lafi.ci", user_type="customer"),
                session=session,
            )
            self.assertEqual(forgot_res["status"], "ok")

            # 5. Réinitialisation avec le code universel 123456
            reset_res = reset_password(
                ResetPasswordRequest(
                    email="kouassi@lafi.ci",
                    code="123456",
                    new_password="NouveauPassword456",
                    user_type="customer",
                ),
                session=session,
            )
            self.assertEqual(reset_res["status"], "ok")

            # 6. Connexion avec le nouveau mot de passe
            relogged = login_customer(
                CustomerLogin(email="kouassi@lafi.ci", password="NouveauPassword456"),
                session=session,
            )
            self.assertEqual(relogged.id, customer.id)

    def test_13_email_verification_for_registration(self):
        """Bloc 3 : Vérifie l'envoi et la validation du code de confirmation par email à l'inscription."""
        with Session(self.test_engine) as session:
            test_email = "nouveau.client@lafi.ci"

            # 1. Envoi du code de vérification pour un nouvel email
            send_res = send_email_verification_code(
                SendEmailCodeRequest(email=test_email, name="Amadou Traoré"),
                session=session,
            )
            self.assertEqual(send_res["status"], "ok")
            self.assertEqual(send_res["email"], test_email)

            # 2. Rejet en cas de format d'email invalide
            with self.assertRaises(Exception):
                send_email_verification_code(
                    SendEmailCodeRequest(email="adresse_invalide_sans_arobase"),
                    session=session,
                )

            # 3. Validation avec le code universel de démonstration soutenance (123456)
            verify_demo = verify_email_code(
                VerifyEmailCodeRequest(email=test_email, code="123456"),
                session=session,
            )
            self.assertTrue(verify_demo["valid"])

            # 4. Échec en cas de mauvais code
            with self.assertRaises(Exception):
                verify_email_code(
                    VerifyEmailCodeRequest(email=test_email, code="999999"),
                    session=session,
                )

    def test_14_login_rate_limiting_and_unified_error(self):
        """Bloc 3 : Vérifie le message d'erreur unifié anti-énumération et le rate limiting (blocage après 5 échecs)."""
        with Session(self.test_engine) as session:
            test_email = "securite.test@lafi.ci"
            correct_pwd = "MonSuperPasswordSecurise123"

            # Création de l'utilisateur
            register_customer(
                CustomerCreate(
                    name="Utilisateur Sécurité",
                    phone="0711223344",
                    address="Plateau",
                    email=test_email,
                    password=correct_pwd,
                ),
                session=session,
            )

            # Nettoyer d'éventuelles tentatives précédentes
            reset_login_attempts(f"customer:email:{test_email}")

            # 1. Test message unifié sur email inexistant
            with self.assertRaises(HTTPException) as ctx1:
                login_customer(
                    CustomerLogin(email="email.inexistant@lafi.ci", password=correct_pwd),
                    session=session,
                )
            self.assertEqual(ctx1.exception.status_code, 401)
            self.assertEqual(ctx1.exception.detail, "Adresse email ou mot de passe incorrect.")

            # 2. Test message unifié sur bon email mais mauvais mot de passe
            with self.assertRaises(HTTPException) as ctx2:
                login_customer(
                    CustomerLogin(email=test_email, password="MauvaisPassword1"),
                    session=session,
                )
            self.assertEqual(ctx2.exception.status_code, 401)
            self.assertEqual(ctx2.exception.detail, "Adresse email ou mot de passe incorrect.")

            # 3. Effectuer 4 tentatives infructueuses supplémentaires (total = 5 échecs)
            for i in range(2, 6):
                with self.assertRaises(HTTPException) as ctx_loop:
                    login_customer(
                        CustomerLogin(email=test_email, password=f"MauvaisPassword{i}"),
                        session=session,
                    )
                self.assertEqual(ctx_loop.exception.status_code, 401)

            # 4. 6ème tentative : doit être bloquée avec code HTTP 429 Too Many Requests
            with self.assertRaises(HTTPException) as ctx_blocked:
                login_customer(
                    CustomerLogin(email=test_email, password=correct_pwd),
                    session=session,
                )
            self.assertEqual(ctx_blocked.exception.status_code, 429)
            self.assertIn("Trop de tentatives", ctx_blocked.exception.detail)

            # 5. Réinitialisation et vérification que la connexion réussit
            reset_login_attempts(f"customer:email:{test_email}")
            logged = login_customer(
                CustomerLogin(email=test_email, password=correct_pwd),
                session=session,
            )
            self.assertEqual(logged.email, test_email)


if __name__ == "__main__":
    unittest.main()
