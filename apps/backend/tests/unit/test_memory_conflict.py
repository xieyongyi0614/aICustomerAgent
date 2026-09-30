from app.engines.memory_conflict import same_topic


class TestSameTopic:
    def test_substring_containment(self):
        assert same_topic("喜欢咖啡", "用户以前喜欢咖啡") is True

    def test_high_overlap_same_topic(self):
        assert same_topic("用户喜欢咖啡", "用户喜欢喝茶") is True

    def test_negation_variant_same_topic(self):
        assert same_topic("用户喜欢咖啡", "用户不喝咖啡") is True

    def test_unrelated_contents_not_same_topic(self):
        assert same_topic("用户在深圳工作", "用户养了一只猫") is False

    def test_threshold_boundary(self):
        assert same_topic("用户喜欢咖啡", "用户喜欢喝茶", threshold=0.99) is False

    def test_empty_content(self):
        assert same_topic("", "用户喜欢咖啡") is False
