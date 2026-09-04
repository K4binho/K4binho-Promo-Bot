import unittest

from k4promo.domain import topics
from k4promo.services import categorizer
from k4promo.services.router import resolve_topic
from k4promo.services.showcase_rules import showcase_eligible


class TopicIdsTest(unittest.TestCase):
    def test_default_ids_match_group(self):
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.MELHORES_DO_DIA], 2194)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.JOGOS], 2195)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.TECNOLOGIA], 2197)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.CASA_COZINHA], 2198)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.MODA_BELEZA], 2201)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.FERRAMENTAS_AUTO], 2202)
        self.assertEqual(topics.DEFAULT_TOPIC_IDS[topics.ACHADINHOS], 2205)

    def test_store_priority_mapping(self):
        p = topics.STORE_TOPIC_PRIORITY
        self.assertEqual(p[topics.MELHORES_DO_DIA], ["mercado_livre", "shopee", "aliexpress", "kabum", "green_man_gaming"])
        self.assertEqual(p[topics.JOGOS], ["green_man_gaming", "steam", "nuuvem"])
        self.assertEqual(p[topics.TECNOLOGIA], ["kabum", "mercado_livre", "aliexpress", "shopee"])
        self.assertEqual(p[topics.CASA_COZINHA], ["shopee", "mercado_livre", "aliexpress", "kabum"])
        self.assertEqual(p[topics.MODA_BELEZA], ["shopee", "aliexpress", "mercado_livre"])
        self.assertEqual(p[topics.FERRAMENTAS_AUTO], ["mercado_livre", "aliexpress", "shopee", "kabum"])
        self.assertEqual(p[topics.ACHADINHOS], ["shopee", "aliexpress", "mercado_livre", "kabum"])

    def test_store_key_normalizes_bot_sources(self):
        self.assertEqual(topics.store_key("ml"), topics.MERCADO_LIVRE)
        self.assertEqual(topics.store_key("ali"), topics.ALIEXPRESS)
        self.assertEqual(topics.store_key("gmg"), topics.GREEN_MAN_GAMING)
        self.assertEqual(topics.store_key("KaBuM"), topics.KABUM)

    def test_store_rank_follows_priority(self):
        self.assertEqual(topics.store_rank(topics.TECNOLOGIA, "kabum"), 0)
        self.assertEqual(topics.store_rank(topics.TECNOLOGIA, "shopee"), 3)
        self.assertGreater(topics.store_rank(topics.MODA_BELEZA, "kabum"), 3)


class ClassifyTitleTest(unittest.TestCase):
    def test_tecnologia(self):
        for title in [
            "Smartphone Samsung Galaxy A15 128GB",
            "SSD Kingston NV2 1TB NVMe",
            "Monitor Gamer LG 27' 144Hz",
            "Fone de Ouvido Bluetooth JBL Tune 510",
            "Smartwatch Xiaomi Redmi Watch 4",
            "Carregador Turbo 25W USB-C Samsung",
            "Controle Sem Fio Xbox Series Carbon Black",
            "Headset Gamer HyperX Cloud II",
            "Câmera de Segurança Wi-Fi Full HD",
        ]:
            self.assertEqual(categorizer.classify_title(title), topics.TECNOLOGIA, title)

    def test_casa_cozinha(self):
        for title in [
            "Air Fryer Mondial 4L Family",
            "Cafeteira Expresso Nespresso Essenza Mini",
            "Ventilador de Mesa Arno 40cm",
            "Jogo de Panelas Tramontina Antiaderente 5 peças",
            "Lâmpada Inteligente Wi-Fi RGB",
            "Kit Organizador de Gaveta 6 peças",
        ]:
            self.assertEqual(categorizer.classify_title(title), topics.CASA_COZINHA, title)

    def test_moda_beleza(self):
        for title in [
            "Tênis Nike Revolution 6 Masculino",
            "Perfume Malbec Eau de Toilette 100ml",
            "Relógio Masculino Casio Vintage",
            "Sérum Vitamina C Facial Skincare",
            "Secador de Cabelo Taiff 2000W",
        ]:
            self.assertEqual(categorizer.classify_title(title), topics.MODA_BELEZA, title)

    def test_ferramentas_auto(self):
        for title in [
            "Furadeira Parafusadeira Bosch 12V com Maleta",
            "Alicate Universal 8' Tramontina",
            "Câmera Veicular Dashcam Full HD",
            "Multímetro Digital Profissional",
            "Compressor de Ar Portátil 12V para Pneu",
            "Kit de Ferramentas 129 peças com Maleta",
        ]:
            self.assertEqual(categorizer.classify_title(title), topics.FERRAMENTAS_AUTO, title)

    def test_achadinhos(self):
        for title in [
            "Boneca Barbie Fashionista",
            "Ração Golden para Cachorro Adulto 15kg",
            "Halteres 5kg Par Academia",
            "Caderno Inteligente A5 Planner",
            "Action Figure Funko Pop",
        ]:
            self.assertEqual(categorizer.classify_title(title), topics.ACHADINHOS, title)

    def test_specific_keyword_wins_over_generic(self):
        # "relogio inteligente" (Tecnologia) vence "relogio" (Moda)
        self.assertEqual(categorizer.classify_title("Relógio Inteligente Smartwatch D20"), topics.TECNOLOGIA)
        # "camera veicular" (Auto) vence "camera" (Tecnologia)
        self.assertEqual(categorizer.classify_title("Camera veicular 1080p"), topics.FERRAMENTAS_AUTO)
        # "suporte veicular" para celular vai para Auto
        self.assertEqual(categorizer.classify_title("Suporte Veicular Magnético para Celular"), topics.FERRAMENTAS_AUTO)

    def test_no_match_returns_empty(self):
        self.assertEqual(categorizer.classify_title("Produto genérico sem categoria"), "")


class ResolveTopicTest(unittest.TestCase):
    def test_game_stores_always_go_to_jogos(self):
        self.assertEqual(resolve_topic("gmg", "Elden Ring"), topics.JOGOS)
        self.assertEqual(resolve_topic("steam", "Furadeira Simulator"), topics.JOGOS)
        self.assertEqual(resolve_topic("nuuvem", "Cyberpunk 2077"), topics.JOGOS)

    def test_physical_stores_never_go_to_jogos(self):
        # controle/headset/console -> Tecnologia
        self.assertEqual(resolve_topic("ml", "Controle DualSense PS5"), topics.TECNOLOGIA)
        self.assertEqual(resolve_topic("kabum", "Headset Gamer Logitech G435"), topics.TECNOLOGIA)
        self.assertEqual(resolve_topic("shopee", "Console Xbox Series S"), topics.TECNOLOGIA)

    def test_unmatched_goes_to_achadinhos(self):
        self.assertEqual(resolve_topic("shopee", "Item aleatório"), topics.ACHADINHOS)

    def test_store_not_allowed_in_topic_falls_back_to_achadinhos(self):
        # KaBuM normalmente não publica em Moda & Beleza
        self.assertEqual(resolve_topic("kabum", "Perfume Importado 100ml"), topics.ACHADINHOS)
        # Shopee pode em Moda & Beleza
        self.assertEqual(resolve_topic("shopee", "Perfume Importado 100ml"), topics.MODA_BELEZA)

    def test_every_physical_store_allowed_in_achadinhos(self):
        for store in topics.PHYSICAL_STORES:
            self.assertTrue(topics.store_allowed(topics.ACHADINHOS, store), store)

    def test_physical_stores_not_allowed_in_jogos(self):
        for store in topics.PHYSICAL_STORES:
            self.assertFalse(topics.store_allowed(topics.JOGOS, store), store)


class ShowcaseEligibilityTest(unittest.TestCase):
    def test_physical_requires_image(self):
        v = showcase_eligible("ml", price=100, discount_percent=60, has_image=False)
        self.assertFalse(v.eligible)

    def test_physical_big_discount(self):
        v = showcase_eligible("ml", price=100, discount_percent=45, has_image=True)
        self.assertTrue(v.eligible)
        self.assertEqual(v.priority, 0)

    def test_physical_soft_criteria_need_two(self):
        only_sales = showcase_eligible("shopee", price=100, discount_percent=20, sales_count=5000, has_image=True)
        self.assertFalse(only_sales.eligible)
        sales_and_shipping = showcase_eligible(
            "shopee", price=100, discount_percent=20, sales_count=5000, free_shipping=True, has_image=True,
        )
        self.assertTrue(sales_and_shipping.eligible)

    def test_physical_coupon_and_lowest_price(self):
        self.assertTrue(showcase_eligible("ali", price=200, coupon_savings=20, has_image=True).eligible)
        self.assertFalse(showcase_eligible("ali", price=200, coupon_savings=2, has_image=True).eligible)
        self.assertTrue(showcase_eligible("kabum", price=200, lowest_price=True, has_image=True).eligible)

    def test_low_rating_blocks(self):
        v = showcase_eligible("ml", price=100, discount_percent=60, rating=3.5, has_image=True)
        self.assertFalse(v.eligible)

    def test_gmg_game_rules(self):
        self.assertTrue(showcase_eligible("gmg", price=0, has_image=True).eligible)
        self.assertTrue(showcase_eligible("gmg", price=20, discount_percent=75, has_image=True).eligible)
        self.assertFalse(showcase_eligible("gmg", price=20, discount_percent=50, has_image=True).eligible)

    def test_steam_nuuvem_need_editorial_value(self):
        plain = showcase_eligible("steam", price=20, discount_percent=80, has_image=True)
        self.assertFalse(plain.eligible)
        strong = showcase_eligible("steam", price=20, discount_percent=80, review_score=95, has_image=True)
        self.assertTrue(strong.eligible)
        lowest = showcase_eligible("nuuvem", price=20, discount_percent=80, lowest_price=True, has_image=True)
        self.assertTrue(lowest.eligible)
        free = showcase_eligible("steam", price=0, has_image=True)
        self.assertTrue(free.eligible)
        # Steam/Nuuvem ficam atrás de todas as lojas com comissão
        self.assertGreater(strong.priority, topics.store_rank(topics.MELHORES_DO_DIA, "gmg"))


if __name__ == "__main__":
    unittest.main()
