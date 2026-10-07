/// 天气城市选择目录（A41 choice-sheet 分组数据）。
///
/// 只列名称、按大区分组；坐标一律由后端地理编码解析，端上不存坐标。
/// 目录外的城市走搜索自由输入行（「用「xxx」」）。
class BriefingCity {
  const BriefingCity(this.name, this.region);

  final String name;
  final String region;
}

const briefingCities = <BriefingCity>[
  BriefingCity('北京', '华北'),
  BriefingCity('天津', '华北'),
  BriefingCity('石家庄', '华北'),
  BriefingCity('太原', '华北'),
  BriefingCity('呼和浩特', '华北'),
  BriefingCity('上海', '华东'),
  BriefingCity('南京', '华东'),
  BriefingCity('苏州', '华东'),
  BriefingCity('杭州', '华东'),
  BriefingCity('宁波', '华东'),
  BriefingCity('温州', '华东'),
  BriefingCity('合肥', '华东'),
  BriefingCity('福州', '华东'),
  BriefingCity('厦门', '华东'),
  BriefingCity('南昌', '华东'),
  BriefingCity('济南', '华东'),
  BriefingCity('青岛', '华东'),
  BriefingCity('广州', '华南'),
  BriefingCity('深圳', '华南'),
  BriefingCity('东莞', '华南'),
  BriefingCity('佛山', '华南'),
  BriefingCity('南宁', '华南'),
  BriefingCity('海口', '华南'),
  BriefingCity('武汉', '华中'),
  BriefingCity('郑州', '华中'),
  BriefingCity('长沙', '华中'),
  BriefingCity('重庆', '西南'),
  BriefingCity('成都', '西南'),
  BriefingCity('贵阳', '西南'),
  BriefingCity('昆明', '西南'),
  BriefingCity('拉萨', '西南'),
  BriefingCity('西安', '西北'),
  BriefingCity('兰州', '西北'),
  BriefingCity('西宁', '西北'),
  BriefingCity('银川', '西北'),
  BriefingCity('乌鲁木齐', '西北'),
  BriefingCity('沈阳', '东北'),
  BriefingCity('大连', '东北'),
  BriefingCity('长春', '东北'),
  BriefingCity('哈尔滨', '东北'),
];
