from sqlmodel import Session, SQLModel, create_engine

engine = create_engine("sqlite:///lafi.db", connect_args={"check_same_thread": False})


def run_migrations():
    """Ajoute les colonnes manquantes aux tables existantes si nécessaire."""
    with engine.connect() as conn:
        # Table shop
        res = conn.exec_driver_sql("PRAGMA table_info(shop)").fetchall()
        if res:
            shop_cols = [r[1] for r in res]
            if "owner_name" not in shop_cols:
                conn.exec_driver_sql("ALTER TABLE shop ADD COLUMN owner_name VARCHAR")
            if "address" not in shop_cols:
                conn.exec_driver_sql("ALTER TABLE shop ADD COLUMN address VARCHAR")
            if "email" not in shop_cols:
                conn.exec_driver_sql("ALTER TABLE shop ADD COLUMN email VARCHAR")
            if "password_hash" not in shop_cols:
                conn.exec_driver_sql("ALTER TABLE shop ADD COLUMN password_hash VARCHAR")

        # Table customers
        res = conn.exec_driver_sql("PRAGMA table_info(customers)").fetchall()
        if res:
            cust_cols = [r[1] for r in res]
            if "email" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN email VARCHAR")
            if "password_hash" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN password_hash VARCHAR")

        # Table article
        res = conn.exec_driver_sql("PRAGMA table_info(article)").fetchall()
        if res:
            article_cols = [r[1] for r in res]
            if "description" not in article_cols:
                conn.exec_driver_sql("ALTER TABLE article ADD COLUMN description VARCHAR")
            if "photos_json" not in article_cols:
                conn.exec_driver_sql("ALTER TABLE article ADD COLUMN photos_json VARCHAR")

        # Table orders
        res = conn.exec_driver_sql("PRAGMA table_info(orders)").fetchall()
        if res:
            order_cols = [r[1] for r in res]
            if "customer_id" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_id INTEGER")
            if "customer_name" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_name VARCHAR")
            if "customer_phone" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_phone VARCHAR")
            if "customer_address" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_address VARCHAR")
            if "pickup_code" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN pickup_code VARCHAR")
            if "customer_lat" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_lat FLOAT")
            if "customer_lng" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN customer_lng FLOAT")
            if "driver_dispatched" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN driver_dispatched BOOLEAN DEFAULT 0")
            if "package_handed_over" not in order_cols:
                conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN package_handed_over BOOLEAN DEFAULT 0")
        conn.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    run_migrations()


def get_session():
    with Session(engine) as session:
        yield session
