// dart format width=80
// ignore_for_file: type=lint
part of 'drift_sample.dart';

class $ScaffoldDriftSamplesTable extends ScaffoldDriftSamples
    with TableInfo<$ScaffoldDriftSamplesTable, ScaffoldDriftSample> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $ScaffoldDriftSamplesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [id];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'scaffold_drift_samples';
  @override
  VerificationContext validateIntegrity(
    Insertable<ScaffoldDriftSample> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  ScaffoldDriftSample map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return ScaffoldDriftSample(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
    );
  }

  @override
  $ScaffoldDriftSamplesTable createAlias(String alias) {
    return $ScaffoldDriftSamplesTable(attachedDatabase, alias);
  }
}

class ScaffoldDriftSample extends DataClass
    implements Insertable<ScaffoldDriftSample> {
  final String id;
  const ScaffoldDriftSample({required this.id});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    return map;
  }

  ScaffoldDriftSamplesCompanion toCompanion(bool nullToAbsent) {
    return ScaffoldDriftSamplesCompanion(id: Value(id));
  }

  factory ScaffoldDriftSample.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return ScaffoldDriftSample(id: serializer.fromJson<String>(json['id']));
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{'id': serializer.toJson<String>(id)};
  }

  ScaffoldDriftSample copyWith({String? id}) =>
      ScaffoldDriftSample(id: id ?? this.id);
  ScaffoldDriftSample copyWithCompanion(ScaffoldDriftSamplesCompanion data) {
    return ScaffoldDriftSample(id: data.id.present ? data.id.value : this.id);
  }

  @override
  String toString() {
    return (StringBuffer('ScaffoldDriftSample(')
          ..write('id: $id')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => id.hashCode;
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is ScaffoldDriftSample && other.id == this.id);
}

class ScaffoldDriftSamplesCompanion
    extends UpdateCompanion<ScaffoldDriftSample> {
  final Value<String> id;
  final Value<int> rowid;
  const ScaffoldDriftSamplesCompanion({
    this.id = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  ScaffoldDriftSamplesCompanion.insert({
    required String id,
    this.rowid = const Value.absent(),
  }) : id = Value(id);
  static Insertable<ScaffoldDriftSample> custom({
    Expression<String>? id,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (rowid != null) 'rowid': rowid,
    });
  }

  ScaffoldDriftSamplesCompanion copyWith({
    Value<String>? id,
    Value<int>? rowid,
  }) {
    return ScaffoldDriftSamplesCompanion(
      id: id ?? this.id,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('ScaffoldDriftSamplesCompanion(')
          ..write('id: $id, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

abstract class _$ScaffoldSampleDb extends GeneratedDatabase {
  _$ScaffoldSampleDb(QueryExecutor e) : super(e);
  $ScaffoldSampleDbManager get managers => $ScaffoldSampleDbManager(this);
  late final $ScaffoldDriftSamplesTable scaffoldDriftSamples =
      $ScaffoldDriftSamplesTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [scaffoldDriftSamples];
}

typedef $$ScaffoldDriftSamplesTableCreateCompanionBuilder =
    ScaffoldDriftSamplesCompanion Function({
      required String id,
      Value<int> rowid,
    });
typedef $$ScaffoldDriftSamplesTableUpdateCompanionBuilder =
    ScaffoldDriftSamplesCompanion Function({
      Value<String> id,
      Value<int> rowid,
    });

class $$ScaffoldDriftSamplesTableFilterComposer
    extends Composer<_$ScaffoldSampleDb, $ScaffoldDriftSamplesTable> {
  $$ScaffoldDriftSamplesTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
    column: $table.id,
    builder: (column) => ColumnFilters(column),
  );
}

class $$ScaffoldDriftSamplesTableOrderingComposer
    extends Composer<_$ScaffoldSampleDb, $ScaffoldDriftSamplesTable> {
  $$ScaffoldDriftSamplesTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
    column: $table.id,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$ScaffoldDriftSamplesTableAnnotationComposer
    extends Composer<_$ScaffoldSampleDb, $ScaffoldDriftSamplesTable> {
  $$ScaffoldDriftSamplesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);
}

class $$ScaffoldDriftSamplesTableTableManager
    extends
        RootTableManager<
          _$ScaffoldSampleDb,
          $ScaffoldDriftSamplesTable,
          ScaffoldDriftSample,
          $$ScaffoldDriftSamplesTableFilterComposer,
          $$ScaffoldDriftSamplesTableOrderingComposer,
          $$ScaffoldDriftSamplesTableAnnotationComposer,
          $$ScaffoldDriftSamplesTableCreateCompanionBuilder,
          $$ScaffoldDriftSamplesTableUpdateCompanionBuilder,
          (
            ScaffoldDriftSample,
            BaseReferences<
              _$ScaffoldSampleDb,
              $ScaffoldDriftSamplesTable,
              ScaffoldDriftSample
            >,
          ),
          ScaffoldDriftSample,
          PrefetchHooks Function()
        > {
  $$ScaffoldDriftSamplesTableTableManager(
    _$ScaffoldSampleDb db,
    $ScaffoldDriftSamplesTable table,
  ) : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$ScaffoldDriftSamplesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$ScaffoldDriftSamplesTableOrderingComposer(
                $db: db,
                $table: table,
              ),
          createComputedFieldComposer: () =>
              $$ScaffoldDriftSamplesTableAnnotationComposer(
                $db: db,
                $table: table,
              ),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => ScaffoldDriftSamplesCompanion(id: id, rowid: rowid),
          createCompanionCallback:
              ({required String id, Value<int> rowid = const Value.absent()}) =>
                  ScaffoldDriftSamplesCompanion.insert(id: id, rowid: rowid),
          withReferenceMapper: (p0) => p0
              .map((e) => (e.readTable(table), BaseReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$ScaffoldDriftSamplesTableProcessedTableManager =
    ProcessedTableManager<
      _$ScaffoldSampleDb,
      $ScaffoldDriftSamplesTable,
      ScaffoldDriftSample,
      $$ScaffoldDriftSamplesTableFilterComposer,
      $$ScaffoldDriftSamplesTableOrderingComposer,
      $$ScaffoldDriftSamplesTableAnnotationComposer,
      $$ScaffoldDriftSamplesTableCreateCompanionBuilder,
      $$ScaffoldDriftSamplesTableUpdateCompanionBuilder,
      (
        ScaffoldDriftSample,
        BaseReferences<
          _$ScaffoldSampleDb,
          $ScaffoldDriftSamplesTable,
          ScaffoldDriftSample
        >,
      ),
      ScaffoldDriftSample,
      PrefetchHooks Function()
    >;

class $ScaffoldSampleDbManager {
  final _$ScaffoldSampleDb _db;
  $ScaffoldSampleDbManager(this._db);
  $$ScaffoldDriftSamplesTableTableManager get scaffoldDriftSamples =>
      $$ScaffoldDriftSamplesTableTableManager(_db, _db.scaffoldDriftSamples);
}
