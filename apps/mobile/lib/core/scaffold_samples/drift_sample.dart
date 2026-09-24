import 'package:drift/drift.dart';

part 'drift_sample.drift.dart';

/// APP-001 样例：drift 独占本文件；输出后缀必须是 `.drift.dart`。
class ScaffoldDriftSamples extends Table {
  TextColumn get id => text()();

  @override
  Set<Column> get primaryKey => {id};
}

@DriftDatabase(tables: [ScaffoldDriftSamples])
class ScaffoldSampleDb extends _$ScaffoldSampleDb {
  ScaffoldSampleDb(super.e);

  @override
  int get schemaVersion => 1;
}
