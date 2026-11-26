// dart format width=80
// ignore_for_file: type=lint
part of 'cache_db.dart';

class $SessionMessagesTable extends SessionMessages
    with TableInfo<$SessionMessagesTable, SessionMessage> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $SessionMessagesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _conversationIdMeta = const VerificationMeta(
    'conversationId',
  );
  @override
  late final GeneratedColumn<String> conversationId = GeneratedColumn<String>(
    'conversation_id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _messageIdMeta = const VerificationMeta(
    'messageId',
  );
  @override
  late final GeneratedColumn<String> messageId = GeneratedColumn<String>(
    'message_id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _roleMeta = const VerificationMeta('role');
  @override
  late final GeneratedColumn<String> role = GeneratedColumn<String>(
    'role',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _contentMeta = const VerificationMeta(
    'content',
  );
  @override
  late final GeneratedColumn<String> content = GeneratedColumn<String>(
    'content',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _eventTimeMeta = const VerificationMeta(
    'eventTime',
  );
  @override
  late final GeneratedColumn<DateTime> eventTime = GeneratedColumn<DateTime>(
    'event_time',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    conversationId,
    messageId,
    role,
    content,
    eventTime,
    cachedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'session_messages';
  @override
  VerificationContext validateIntegrity(
    Insertable<SessionMessage> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('conversation_id')) {
      context.handle(
        _conversationIdMeta,
        conversationId.isAcceptableOrUnknown(
          data['conversation_id']!,
          _conversationIdMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_conversationIdMeta);
    }
    if (data.containsKey('message_id')) {
      context.handle(
        _messageIdMeta,
        messageId.isAcceptableOrUnknown(data['message_id']!, _messageIdMeta),
      );
    } else if (isInserting) {
      context.missing(_messageIdMeta);
    }
    if (data.containsKey('role')) {
      context.handle(
        _roleMeta,
        role.isAcceptableOrUnknown(data['role']!, _roleMeta),
      );
    } else if (isInserting) {
      context.missing(_roleMeta);
    }
    if (data.containsKey('content')) {
      context.handle(
        _contentMeta,
        content.isAcceptableOrUnknown(data['content']!, _contentMeta),
      );
    } else if (isInserting) {
      context.missing(_contentMeta);
    }
    if (data.containsKey('event_time')) {
      context.handle(
        _eventTimeMeta,
        eventTime.isAcceptableOrUnknown(data['event_time']!, _eventTimeMeta),
      );
    } else if (isInserting) {
      context.missing(_eventTimeMeta);
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {conversationId, messageId};
  @override
  SessionMessage map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return SessionMessage(
      conversationId: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}conversation_id'],
      )!,
      messageId: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}message_id'],
      )!,
      role: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}role'],
      )!,
      content: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}content'],
      )!,
      eventTime: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}event_time'],
      )!,
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $SessionMessagesTable createAlias(String alias) {
    return $SessionMessagesTable(attachedDatabase, alias);
  }
}

class SessionMessage extends DataClass implements Insertable<SessionMessage> {
  final String conversationId;
  final String messageId;
  final String role;
  final String content;
  final DateTime eventTime;
  final DateTime cachedAt;
  const SessionMessage({
    required this.conversationId,
    required this.messageId,
    required this.role,
    required this.content,
    required this.eventTime,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['conversation_id'] = Variable<String>(conversationId);
    map['message_id'] = Variable<String>(messageId);
    map['role'] = Variable<String>(role);
    map['content'] = Variable<String>(content);
    map['event_time'] = Variable<DateTime>(eventTime);
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  SessionMessagesCompanion toCompanion(bool nullToAbsent) {
    return SessionMessagesCompanion(
      conversationId: Value(conversationId),
      messageId: Value(messageId),
      role: Value(role),
      content: Value(content),
      eventTime: Value(eventTime),
      cachedAt: Value(cachedAt),
    );
  }

  factory SessionMessage.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return SessionMessage(
      conversationId: serializer.fromJson<String>(json['conversationId']),
      messageId: serializer.fromJson<String>(json['messageId']),
      role: serializer.fromJson<String>(json['role']),
      content: serializer.fromJson<String>(json['content']),
      eventTime: serializer.fromJson<DateTime>(json['eventTime']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'conversationId': serializer.toJson<String>(conversationId),
      'messageId': serializer.toJson<String>(messageId),
      'role': serializer.toJson<String>(role),
      'content': serializer.toJson<String>(content),
      'eventTime': serializer.toJson<DateTime>(eventTime),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  SessionMessage copyWith({
    String? conversationId,
    String? messageId,
    String? role,
    String? content,
    DateTime? eventTime,
    DateTime? cachedAt,
  }) => SessionMessage(
    conversationId: conversationId ?? this.conversationId,
    messageId: messageId ?? this.messageId,
    role: role ?? this.role,
    content: content ?? this.content,
    eventTime: eventTime ?? this.eventTime,
    cachedAt: cachedAt ?? this.cachedAt,
  );
  SessionMessage copyWithCompanion(SessionMessagesCompanion data) {
    return SessionMessage(
      conversationId: data.conversationId.present
          ? data.conversationId.value
          : this.conversationId,
      messageId: data.messageId.present ? data.messageId.value : this.messageId,
      role: data.role.present ? data.role.value : this.role,
      content: data.content.present ? data.content.value : this.content,
      eventTime: data.eventTime.present ? data.eventTime.value : this.eventTime,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('SessionMessage(')
          ..write('conversationId: $conversationId, ')
          ..write('messageId: $messageId, ')
          ..write('role: $role, ')
          ..write('content: $content, ')
          ..write('eventTime: $eventTime, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
    conversationId,
    messageId,
    role,
    content,
    eventTime,
    cachedAt,
  );
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is SessionMessage &&
          other.conversationId == this.conversationId &&
          other.messageId == this.messageId &&
          other.role == this.role &&
          other.content == this.content &&
          other.eventTime == this.eventTime &&
          other.cachedAt == this.cachedAt);
}

class SessionMessagesCompanion extends UpdateCompanion<SessionMessage> {
  final Value<String> conversationId;
  final Value<String> messageId;
  final Value<String> role;
  final Value<String> content;
  final Value<DateTime> eventTime;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const SessionMessagesCompanion({
    this.conversationId = const Value.absent(),
    this.messageId = const Value.absent(),
    this.role = const Value.absent(),
    this.content = const Value.absent(),
    this.eventTime = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  SessionMessagesCompanion.insert({
    required String conversationId,
    required String messageId,
    required String role,
    required String content,
    required DateTime eventTime,
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : conversationId = Value(conversationId),
       messageId = Value(messageId),
       role = Value(role),
       content = Value(content),
       eventTime = Value(eventTime),
       cachedAt = Value(cachedAt);
  static Insertable<SessionMessage> custom({
    Expression<String>? conversationId,
    Expression<String>? messageId,
    Expression<String>? role,
    Expression<String>? content,
    Expression<DateTime>? eventTime,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (conversationId != null) 'conversation_id': conversationId,
      if (messageId != null) 'message_id': messageId,
      if (role != null) 'role': role,
      if (content != null) 'content': content,
      if (eventTime != null) 'event_time': eventTime,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  SessionMessagesCompanion copyWith({
    Value<String>? conversationId,
    Value<String>? messageId,
    Value<String>? role,
    Value<String>? content,
    Value<DateTime>? eventTime,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return SessionMessagesCompanion(
      conversationId: conversationId ?? this.conversationId,
      messageId: messageId ?? this.messageId,
      role: role ?? this.role,
      content: content ?? this.content,
      eventTime: eventTime ?? this.eventTime,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (conversationId.present) {
      map['conversation_id'] = Variable<String>(conversationId.value);
    }
    if (messageId.present) {
      map['message_id'] = Variable<String>(messageId.value);
    }
    if (role.present) {
      map['role'] = Variable<String>(role.value);
    }
    if (content.present) {
      map['content'] = Variable<String>(content.value);
    }
    if (eventTime.present) {
      map['event_time'] = Variable<DateTime>(eventTime.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('SessionMessagesCompanion(')
          ..write('conversationId: $conversationId, ')
          ..write('messageId: $messageId, ')
          ..write('role: $role, ')
          ..write('content: $content, ')
          ..write('eventTime: $eventTime, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $MemoryItemsTable extends MemoryItems
    with TableInfo<$MemoryItemsTable, MemoryItem> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $MemoryItemsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _kindMeta = const VerificationMeta('kind');
  @override
  late final GeneratedColumn<String> kind = GeneratedColumn<String>(
    'kind',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _labelMeta = const VerificationMeta('label');
  @override
  late final GeneratedColumn<String> label = GeneratedColumn<String>(
    'label',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _contentMeta = const VerificationMeta(
    'content',
  );
  @override
  late final GeneratedColumn<String> content = GeneratedColumn<String>(
    'content',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _sourceSummaryMeta = const VerificationMeta(
    'sourceSummary',
  );
  @override
  late final GeneratedColumn<String> sourceSummary = GeneratedColumn<String>(
    'source_summary',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _lastUpdatedMeta = const VerificationMeta(
    'lastUpdated',
  );
  @override
  late final GeneratedColumn<DateTime> lastUpdated = GeneratedColumn<DateTime>(
    'last_updated',
    aliasedName,
    true,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _usageReceiptsJsonMeta = const VerificationMeta(
    'usageReceiptsJson',
  );
  @override
  late final GeneratedColumn<String> usageReceiptsJson =
      GeneratedColumn<String>(
        'usage_receipts_json',
        aliasedName,
        true,
        type: DriftSqlType.string,
        requiredDuringInsert: false,
      );
  static const VerificationMeta _activeMeta = const VerificationMeta('active');
  @override
  late final GeneratedColumn<bool> active = GeneratedColumn<bool>(
    'active',
    aliasedName,
    false,
    type: DriftSqlType.bool,
    requiredDuringInsert: false,
    defaultConstraints: GeneratedColumn.constraintIsAlways(
      'CHECK ("active" IN (0, 1))',
    ),
    defaultValue: const Constant(true),
  );
  static const VerificationMeta _forgottenMeta = const VerificationMeta(
    'forgotten',
  );
  @override
  late final GeneratedColumn<bool> forgotten = GeneratedColumn<bool>(
    'forgotten',
    aliasedName,
    false,
    type: DriftSqlType.bool,
    requiredDuringInsert: false,
    defaultConstraints: GeneratedColumn.constraintIsAlways(
      'CHECK ("forgotten" IN (0, 1))',
    ),
    defaultValue: const Constant(false),
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    id,
    kind,
    label,
    content,
    sourceSummary,
    lastUpdated,
    usageReceiptsJson,
    active,
    forgotten,
    cachedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'memory_items';
  @override
  VerificationContext validateIntegrity(
    Insertable<MemoryItem> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('kind')) {
      context.handle(
        _kindMeta,
        kind.isAcceptableOrUnknown(data['kind']!, _kindMeta),
      );
    } else if (isInserting) {
      context.missing(_kindMeta);
    }
    if (data.containsKey('label')) {
      context.handle(
        _labelMeta,
        label.isAcceptableOrUnknown(data['label']!, _labelMeta),
      );
    } else if (isInserting) {
      context.missing(_labelMeta);
    }
    if (data.containsKey('content')) {
      context.handle(
        _contentMeta,
        content.isAcceptableOrUnknown(data['content']!, _contentMeta),
      );
    } else if (isInserting) {
      context.missing(_contentMeta);
    }
    if (data.containsKey('source_summary')) {
      context.handle(
        _sourceSummaryMeta,
        sourceSummary.isAcceptableOrUnknown(
          data['source_summary']!,
          _sourceSummaryMeta,
        ),
      );
    }
    if (data.containsKey('last_updated')) {
      context.handle(
        _lastUpdatedMeta,
        lastUpdated.isAcceptableOrUnknown(
          data['last_updated']!,
          _lastUpdatedMeta,
        ),
      );
    }
    if (data.containsKey('usage_receipts_json')) {
      context.handle(
        _usageReceiptsJsonMeta,
        usageReceiptsJson.isAcceptableOrUnknown(
          data['usage_receipts_json']!,
          _usageReceiptsJsonMeta,
        ),
      );
    }
    if (data.containsKey('active')) {
      context.handle(
        _activeMeta,
        active.isAcceptableOrUnknown(data['active']!, _activeMeta),
      );
    }
    if (data.containsKey('forgotten')) {
      context.handle(
        _forgottenMeta,
        forgotten.isAcceptableOrUnknown(data['forgotten']!, _forgottenMeta),
      );
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  MemoryItem map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return MemoryItem(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      kind: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}kind'],
      )!,
      label: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}label'],
      )!,
      content: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}content'],
      )!,
      sourceSummary: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}source_summary'],
      ),
      lastUpdated: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}last_updated'],
      ),
      usageReceiptsJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}usage_receipts_json'],
      ),
      active: attachedDatabase.typeMapping.read(
        DriftSqlType.bool,
        data['${effectivePrefix}active'],
      )!,
      forgotten: attachedDatabase.typeMapping.read(
        DriftSqlType.bool,
        data['${effectivePrefix}forgotten'],
      )!,
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $MemoryItemsTable createAlias(String alias) {
    return $MemoryItemsTable(attachedDatabase, alias);
  }
}

class MemoryItem extends DataClass implements Insertable<MemoryItem> {
  final String id;
  final String kind;
  final String label;
  final String content;
  final String? sourceSummary;
  final DateTime? lastUpdated;
  final String? usageReceiptsJson;
  final bool active;
  final bool forgotten;
  final DateTime cachedAt;
  const MemoryItem({
    required this.id,
    required this.kind,
    required this.label,
    required this.content,
    this.sourceSummary,
    this.lastUpdated,
    this.usageReceiptsJson,
    required this.active,
    required this.forgotten,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['kind'] = Variable<String>(kind);
    map['label'] = Variable<String>(label);
    map['content'] = Variable<String>(content);
    if (!nullToAbsent || sourceSummary != null) {
      map['source_summary'] = Variable<String>(sourceSummary);
    }
    if (!nullToAbsent || lastUpdated != null) {
      map['last_updated'] = Variable<DateTime>(lastUpdated);
    }
    if (!nullToAbsent || usageReceiptsJson != null) {
      map['usage_receipts_json'] = Variable<String>(usageReceiptsJson);
    }
    map['active'] = Variable<bool>(active);
    map['forgotten'] = Variable<bool>(forgotten);
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  MemoryItemsCompanion toCompanion(bool nullToAbsent) {
    return MemoryItemsCompanion(
      id: Value(id),
      kind: Value(kind),
      label: Value(label),
      content: Value(content),
      sourceSummary: sourceSummary == null && nullToAbsent
          ? const Value.absent()
          : Value(sourceSummary),
      lastUpdated: lastUpdated == null && nullToAbsent
          ? const Value.absent()
          : Value(lastUpdated),
      usageReceiptsJson: usageReceiptsJson == null && nullToAbsent
          ? const Value.absent()
          : Value(usageReceiptsJson),
      active: Value(active),
      forgotten: Value(forgotten),
      cachedAt: Value(cachedAt),
    );
  }

  factory MemoryItem.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return MemoryItem(
      id: serializer.fromJson<String>(json['id']),
      kind: serializer.fromJson<String>(json['kind']),
      label: serializer.fromJson<String>(json['label']),
      content: serializer.fromJson<String>(json['content']),
      sourceSummary: serializer.fromJson<String?>(json['sourceSummary']),
      lastUpdated: serializer.fromJson<DateTime?>(json['lastUpdated']),
      usageReceiptsJson: serializer.fromJson<String?>(
        json['usageReceiptsJson'],
      ),
      active: serializer.fromJson<bool>(json['active']),
      forgotten: serializer.fromJson<bool>(json['forgotten']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'kind': serializer.toJson<String>(kind),
      'label': serializer.toJson<String>(label),
      'content': serializer.toJson<String>(content),
      'sourceSummary': serializer.toJson<String?>(sourceSummary),
      'lastUpdated': serializer.toJson<DateTime?>(lastUpdated),
      'usageReceiptsJson': serializer.toJson<String?>(usageReceiptsJson),
      'active': serializer.toJson<bool>(active),
      'forgotten': serializer.toJson<bool>(forgotten),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  MemoryItem copyWith({
    String? id,
    String? kind,
    String? label,
    String? content,
    Value<String?> sourceSummary = const Value.absent(),
    Value<DateTime?> lastUpdated = const Value.absent(),
    Value<String?> usageReceiptsJson = const Value.absent(),
    bool? active,
    bool? forgotten,
    DateTime? cachedAt,
  }) => MemoryItem(
    id: id ?? this.id,
    kind: kind ?? this.kind,
    label: label ?? this.label,
    content: content ?? this.content,
    sourceSummary: sourceSummary.present
        ? sourceSummary.value
        : this.sourceSummary,
    lastUpdated: lastUpdated.present ? lastUpdated.value : this.lastUpdated,
    usageReceiptsJson: usageReceiptsJson.present
        ? usageReceiptsJson.value
        : this.usageReceiptsJson,
    active: active ?? this.active,
    forgotten: forgotten ?? this.forgotten,
    cachedAt: cachedAt ?? this.cachedAt,
  );
  MemoryItem copyWithCompanion(MemoryItemsCompanion data) {
    return MemoryItem(
      id: data.id.present ? data.id.value : this.id,
      kind: data.kind.present ? data.kind.value : this.kind,
      label: data.label.present ? data.label.value : this.label,
      content: data.content.present ? data.content.value : this.content,
      sourceSummary: data.sourceSummary.present
          ? data.sourceSummary.value
          : this.sourceSummary,
      lastUpdated: data.lastUpdated.present
          ? data.lastUpdated.value
          : this.lastUpdated,
      usageReceiptsJson: data.usageReceiptsJson.present
          ? data.usageReceiptsJson.value
          : this.usageReceiptsJson,
      active: data.active.present ? data.active.value : this.active,
      forgotten: data.forgotten.present ? data.forgotten.value : this.forgotten,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('MemoryItem(')
          ..write('id: $id, ')
          ..write('kind: $kind, ')
          ..write('label: $label, ')
          ..write('content: $content, ')
          ..write('sourceSummary: $sourceSummary, ')
          ..write('lastUpdated: $lastUpdated, ')
          ..write('usageReceiptsJson: $usageReceiptsJson, ')
          ..write('active: $active, ')
          ..write('forgotten: $forgotten, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
    id,
    kind,
    label,
    content,
    sourceSummary,
    lastUpdated,
    usageReceiptsJson,
    active,
    forgotten,
    cachedAt,
  );
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is MemoryItem &&
          other.id == this.id &&
          other.kind == this.kind &&
          other.label == this.label &&
          other.content == this.content &&
          other.sourceSummary == this.sourceSummary &&
          other.lastUpdated == this.lastUpdated &&
          other.usageReceiptsJson == this.usageReceiptsJson &&
          other.active == this.active &&
          other.forgotten == this.forgotten &&
          other.cachedAt == this.cachedAt);
}

class MemoryItemsCompanion extends UpdateCompanion<MemoryItem> {
  final Value<String> id;
  final Value<String> kind;
  final Value<String> label;
  final Value<String> content;
  final Value<String?> sourceSummary;
  final Value<DateTime?> lastUpdated;
  final Value<String?> usageReceiptsJson;
  final Value<bool> active;
  final Value<bool> forgotten;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const MemoryItemsCompanion({
    this.id = const Value.absent(),
    this.kind = const Value.absent(),
    this.label = const Value.absent(),
    this.content = const Value.absent(),
    this.sourceSummary = const Value.absent(),
    this.lastUpdated = const Value.absent(),
    this.usageReceiptsJson = const Value.absent(),
    this.active = const Value.absent(),
    this.forgotten = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  MemoryItemsCompanion.insert({
    required String id,
    required String kind,
    required String label,
    required String content,
    this.sourceSummary = const Value.absent(),
    this.lastUpdated = const Value.absent(),
    this.usageReceiptsJson = const Value.absent(),
    this.active = const Value.absent(),
    this.forgotten = const Value.absent(),
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       kind = Value(kind),
       label = Value(label),
       content = Value(content),
       cachedAt = Value(cachedAt);
  static Insertable<MemoryItem> custom({
    Expression<String>? id,
    Expression<String>? kind,
    Expression<String>? label,
    Expression<String>? content,
    Expression<String>? sourceSummary,
    Expression<DateTime>? lastUpdated,
    Expression<String>? usageReceiptsJson,
    Expression<bool>? active,
    Expression<bool>? forgotten,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (kind != null) 'kind': kind,
      if (label != null) 'label': label,
      if (content != null) 'content': content,
      if (sourceSummary != null) 'source_summary': sourceSummary,
      if (lastUpdated != null) 'last_updated': lastUpdated,
      if (usageReceiptsJson != null) 'usage_receipts_json': usageReceiptsJson,
      if (active != null) 'active': active,
      if (forgotten != null) 'forgotten': forgotten,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  MemoryItemsCompanion copyWith({
    Value<String>? id,
    Value<String>? kind,
    Value<String>? label,
    Value<String>? content,
    Value<String?>? sourceSummary,
    Value<DateTime?>? lastUpdated,
    Value<String?>? usageReceiptsJson,
    Value<bool>? active,
    Value<bool>? forgotten,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return MemoryItemsCompanion(
      id: id ?? this.id,
      kind: kind ?? this.kind,
      label: label ?? this.label,
      content: content ?? this.content,
      sourceSummary: sourceSummary ?? this.sourceSummary,
      lastUpdated: lastUpdated ?? this.lastUpdated,
      usageReceiptsJson: usageReceiptsJson ?? this.usageReceiptsJson,
      active: active ?? this.active,
      forgotten: forgotten ?? this.forgotten,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (kind.present) {
      map['kind'] = Variable<String>(kind.value);
    }
    if (label.present) {
      map['label'] = Variable<String>(label.value);
    }
    if (content.present) {
      map['content'] = Variable<String>(content.value);
    }
    if (sourceSummary.present) {
      map['source_summary'] = Variable<String>(sourceSummary.value);
    }
    if (lastUpdated.present) {
      map['last_updated'] = Variable<DateTime>(lastUpdated.value);
    }
    if (usageReceiptsJson.present) {
      map['usage_receipts_json'] = Variable<String>(usageReceiptsJson.value);
    }
    if (active.present) {
      map['active'] = Variable<bool>(active.value);
    }
    if (forgotten.present) {
      map['forgotten'] = Variable<bool>(forgotten.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('MemoryItemsCompanion(')
          ..write('id: $id, ')
          ..write('kind: $kind, ')
          ..write('label: $label, ')
          ..write('content: $content, ')
          ..write('sourceSummary: $sourceSummary, ')
          ..write('lastUpdated: $lastUpdated, ')
          ..write('usageReceiptsJson: $usageReceiptsJson, ')
          ..write('active: $active, ')
          ..write('forgotten: $forgotten, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $LedgerSummariesTable extends LedgerSummaries
    with TableInfo<$LedgerSummariesTable, LedgerSummary> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $LedgerSummariesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _formattedAmountMeta = const VerificationMeta(
    'formattedAmount',
  );
  @override
  late final GeneratedColumn<String> formattedAmount = GeneratedColumn<String>(
    'formatted_amount',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    id,
    payloadJson,
    formattedAmount,
    cachedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'ledger_summaries';
  @override
  VerificationContext validateIntegrity(
    Insertable<LedgerSummary> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_payloadJsonMeta);
    }
    if (data.containsKey('formatted_amount')) {
      context.handle(
        _formattedAmountMeta,
        formattedAmount.isAcceptableOrUnknown(
          data['formatted_amount']!,
          _formattedAmountMeta,
        ),
      );
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  LedgerSummary map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return LedgerSummary(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      )!,
      formattedAmount: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}formatted_amount'],
      ),
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $LedgerSummariesTable createAlias(String alias) {
    return $LedgerSummariesTable(attachedDatabase, alias);
  }
}

class LedgerSummary extends DataClass implements Insertable<LedgerSummary> {
  final String id;
  final String payloadJson;
  final String? formattedAmount;
  final DateTime cachedAt;
  const LedgerSummary({
    required this.id,
    required this.payloadJson,
    this.formattedAmount,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['payload_json'] = Variable<String>(payloadJson);
    if (!nullToAbsent || formattedAmount != null) {
      map['formatted_amount'] = Variable<String>(formattedAmount);
    }
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  LedgerSummariesCompanion toCompanion(bool nullToAbsent) {
    return LedgerSummariesCompanion(
      id: Value(id),
      payloadJson: Value(payloadJson),
      formattedAmount: formattedAmount == null && nullToAbsent
          ? const Value.absent()
          : Value(formattedAmount),
      cachedAt: Value(cachedAt),
    );
  }

  factory LedgerSummary.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return LedgerSummary(
      id: serializer.fromJson<String>(json['id']),
      payloadJson: serializer.fromJson<String>(json['payloadJson']),
      formattedAmount: serializer.fromJson<String?>(json['formattedAmount']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'payloadJson': serializer.toJson<String>(payloadJson),
      'formattedAmount': serializer.toJson<String?>(formattedAmount),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  LedgerSummary copyWith({
    String? id,
    String? payloadJson,
    Value<String?> formattedAmount = const Value.absent(),
    DateTime? cachedAt,
  }) => LedgerSummary(
    id: id ?? this.id,
    payloadJson: payloadJson ?? this.payloadJson,
    formattedAmount: formattedAmount.present
        ? formattedAmount.value
        : this.formattedAmount,
    cachedAt: cachedAt ?? this.cachedAt,
  );
  LedgerSummary copyWithCompanion(LedgerSummariesCompanion data) {
    return LedgerSummary(
      id: data.id.present ? data.id.value : this.id,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      formattedAmount: data.formattedAmount.present
          ? data.formattedAmount.value
          : this.formattedAmount,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('LedgerSummary(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('formattedAmount: $formattedAmount, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, payloadJson, formattedAmount, cachedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is LedgerSummary &&
          other.id == this.id &&
          other.payloadJson == this.payloadJson &&
          other.formattedAmount == this.formattedAmount &&
          other.cachedAt == this.cachedAt);
}

class LedgerSummariesCompanion extends UpdateCompanion<LedgerSummary> {
  final Value<String> id;
  final Value<String> payloadJson;
  final Value<String?> formattedAmount;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const LedgerSummariesCompanion({
    this.id = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.formattedAmount = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  LedgerSummariesCompanion.insert({
    required String id,
    required String payloadJson,
    this.formattedAmount = const Value.absent(),
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       payloadJson = Value(payloadJson),
       cachedAt = Value(cachedAt);
  static Insertable<LedgerSummary> custom({
    Expression<String>? id,
    Expression<String>? payloadJson,
    Expression<String>? formattedAmount,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (formattedAmount != null) 'formatted_amount': formattedAmount,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  LedgerSummariesCompanion copyWith({
    Value<String>? id,
    Value<String>? payloadJson,
    Value<String?>? formattedAmount,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return LedgerSummariesCompanion(
      id: id ?? this.id,
      payloadJson: payloadJson ?? this.payloadJson,
      formattedAmount: formattedAmount ?? this.formattedAmount,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (formattedAmount.present) {
      map['formatted_amount'] = Variable<String>(formattedAmount.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('LedgerSummariesCompanion(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('formattedAmount: $formattedAmount, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $LedgerEntriesTable extends LedgerEntries
    with TableInfo<$LedgerEntriesTable, LedgerEntry> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $LedgerEntriesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _titleMeta = const VerificationMeta('title');
  @override
  late final GeneratedColumn<String> title = GeneratedColumn<String>(
    'title',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _formattedAmountMeta = const VerificationMeta(
    'formattedAmount',
  );
  @override
  late final GeneratedColumn<String> formattedAmount = GeneratedColumn<String>(
    'formatted_amount',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _sourceMeta = const VerificationMeta('source');
  @override
  late final GeneratedColumn<String> source = GeneratedColumn<String>(
    'source',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _eventTimeMeta = const VerificationMeta(
    'eventTime',
  );
  @override
  late final GeneratedColumn<DateTime> eventTime = GeneratedColumn<DateTime>(
    'event_time',
    aliasedName,
    true,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    id,
    title,
    formattedAmount,
    source,
    eventTime,
    cachedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'ledger_entries';
  @override
  VerificationContext validateIntegrity(
    Insertable<LedgerEntry> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('title')) {
      context.handle(
        _titleMeta,
        title.isAcceptableOrUnknown(data['title']!, _titleMeta),
      );
    } else if (isInserting) {
      context.missing(_titleMeta);
    }
    if (data.containsKey('formatted_amount')) {
      context.handle(
        _formattedAmountMeta,
        formattedAmount.isAcceptableOrUnknown(
          data['formatted_amount']!,
          _formattedAmountMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_formattedAmountMeta);
    }
    if (data.containsKey('source')) {
      context.handle(
        _sourceMeta,
        source.isAcceptableOrUnknown(data['source']!, _sourceMeta),
      );
    }
    if (data.containsKey('event_time')) {
      context.handle(
        _eventTimeMeta,
        eventTime.isAcceptableOrUnknown(data['event_time']!, _eventTimeMeta),
      );
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  LedgerEntry map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return LedgerEntry(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      title: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}title'],
      )!,
      formattedAmount: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}formatted_amount'],
      )!,
      source: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}source'],
      ),
      eventTime: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}event_time'],
      ),
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $LedgerEntriesTable createAlias(String alias) {
    return $LedgerEntriesTable(attachedDatabase, alias);
  }
}

class LedgerEntry extends DataClass implements Insertable<LedgerEntry> {
  final String id;
  final String title;
  final String formattedAmount;
  final String? source;
  final DateTime? eventTime;
  final DateTime cachedAt;
  const LedgerEntry({
    required this.id,
    required this.title,
    required this.formattedAmount,
    this.source,
    this.eventTime,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['title'] = Variable<String>(title);
    map['formatted_amount'] = Variable<String>(formattedAmount);
    if (!nullToAbsent || source != null) {
      map['source'] = Variable<String>(source);
    }
    if (!nullToAbsent || eventTime != null) {
      map['event_time'] = Variable<DateTime>(eventTime);
    }
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  LedgerEntriesCompanion toCompanion(bool nullToAbsent) {
    return LedgerEntriesCompanion(
      id: Value(id),
      title: Value(title),
      formattedAmount: Value(formattedAmount),
      source: source == null && nullToAbsent
          ? const Value.absent()
          : Value(source),
      eventTime: eventTime == null && nullToAbsent
          ? const Value.absent()
          : Value(eventTime),
      cachedAt: Value(cachedAt),
    );
  }

  factory LedgerEntry.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return LedgerEntry(
      id: serializer.fromJson<String>(json['id']),
      title: serializer.fromJson<String>(json['title']),
      formattedAmount: serializer.fromJson<String>(json['formattedAmount']),
      source: serializer.fromJson<String?>(json['source']),
      eventTime: serializer.fromJson<DateTime?>(json['eventTime']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'title': serializer.toJson<String>(title),
      'formattedAmount': serializer.toJson<String>(formattedAmount),
      'source': serializer.toJson<String?>(source),
      'eventTime': serializer.toJson<DateTime?>(eventTime),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  LedgerEntry copyWith({
    String? id,
    String? title,
    String? formattedAmount,
    Value<String?> source = const Value.absent(),
    Value<DateTime?> eventTime = const Value.absent(),
    DateTime? cachedAt,
  }) => LedgerEntry(
    id: id ?? this.id,
    title: title ?? this.title,
    formattedAmount: formattedAmount ?? this.formattedAmount,
    source: source.present ? source.value : this.source,
    eventTime: eventTime.present ? eventTime.value : this.eventTime,
    cachedAt: cachedAt ?? this.cachedAt,
  );
  LedgerEntry copyWithCompanion(LedgerEntriesCompanion data) {
    return LedgerEntry(
      id: data.id.present ? data.id.value : this.id,
      title: data.title.present ? data.title.value : this.title,
      formattedAmount: data.formattedAmount.present
          ? data.formattedAmount.value
          : this.formattedAmount,
      source: data.source.present ? data.source.value : this.source,
      eventTime: data.eventTime.present ? data.eventTime.value : this.eventTime,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('LedgerEntry(')
          ..write('id: $id, ')
          ..write('title: $title, ')
          ..write('formattedAmount: $formattedAmount, ')
          ..write('source: $source, ')
          ..write('eventTime: $eventTime, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode =>
      Object.hash(id, title, formattedAmount, source, eventTime, cachedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is LedgerEntry &&
          other.id == this.id &&
          other.title == this.title &&
          other.formattedAmount == this.formattedAmount &&
          other.source == this.source &&
          other.eventTime == this.eventTime &&
          other.cachedAt == this.cachedAt);
}

class LedgerEntriesCompanion extends UpdateCompanion<LedgerEntry> {
  final Value<String> id;
  final Value<String> title;
  final Value<String> formattedAmount;
  final Value<String?> source;
  final Value<DateTime?> eventTime;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const LedgerEntriesCompanion({
    this.id = const Value.absent(),
    this.title = const Value.absent(),
    this.formattedAmount = const Value.absent(),
    this.source = const Value.absent(),
    this.eventTime = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  LedgerEntriesCompanion.insert({
    required String id,
    required String title,
    required String formattedAmount,
    this.source = const Value.absent(),
    this.eventTime = const Value.absent(),
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       title = Value(title),
       formattedAmount = Value(formattedAmount),
       cachedAt = Value(cachedAt);
  static Insertable<LedgerEntry> custom({
    Expression<String>? id,
    Expression<String>? title,
    Expression<String>? formattedAmount,
    Expression<String>? source,
    Expression<DateTime>? eventTime,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (title != null) 'title': title,
      if (formattedAmount != null) 'formatted_amount': formattedAmount,
      if (source != null) 'source': source,
      if (eventTime != null) 'event_time': eventTime,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  LedgerEntriesCompanion copyWith({
    Value<String>? id,
    Value<String>? title,
    Value<String>? formattedAmount,
    Value<String?>? source,
    Value<DateTime?>? eventTime,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return LedgerEntriesCompanion(
      id: id ?? this.id,
      title: title ?? this.title,
      formattedAmount: formattedAmount ?? this.formattedAmount,
      source: source ?? this.source,
      eventTime: eventTime ?? this.eventTime,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (title.present) {
      map['title'] = Variable<String>(title.value);
    }
    if (formattedAmount.present) {
      map['formatted_amount'] = Variable<String>(formattedAmount.value);
    }
    if (source.present) {
      map['source'] = Variable<String>(source.value);
    }
    if (eventTime.present) {
      map['event_time'] = Variable<DateTime>(eventTime.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('LedgerEntriesCompanion(')
          ..write('id: $id, ')
          ..write('title: $title, ')
          ..write('formattedAmount: $formattedAmount, ')
          ..write('source: $source, ')
          ..write('eventTime: $eventTime, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $HomeSummariesTable extends HomeSummaries
    with TableInfo<$HomeSummariesTable, HomeSummary> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $HomeSummariesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [id, payloadJson, cachedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'home_summaries';
  @override
  VerificationContext validateIntegrity(
    Insertable<HomeSummary> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_payloadJsonMeta);
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  HomeSummary map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return HomeSummary(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      )!,
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $HomeSummariesTable createAlias(String alias) {
    return $HomeSummariesTable(attachedDatabase, alias);
  }
}

class HomeSummary extends DataClass implements Insertable<HomeSummary> {
  final String id;
  final String payloadJson;
  final DateTime cachedAt;
  const HomeSummary({
    required this.id,
    required this.payloadJson,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['payload_json'] = Variable<String>(payloadJson);
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  HomeSummariesCompanion toCompanion(bool nullToAbsent) {
    return HomeSummariesCompanion(
      id: Value(id),
      payloadJson: Value(payloadJson),
      cachedAt: Value(cachedAt),
    );
  }

  factory HomeSummary.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return HomeSummary(
      id: serializer.fromJson<String>(json['id']),
      payloadJson: serializer.fromJson<String>(json['payloadJson']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'payloadJson': serializer.toJson<String>(payloadJson),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  HomeSummary copyWith({String? id, String? payloadJson, DateTime? cachedAt}) =>
      HomeSummary(
        id: id ?? this.id,
        payloadJson: payloadJson ?? this.payloadJson,
        cachedAt: cachedAt ?? this.cachedAt,
      );
  HomeSummary copyWithCompanion(HomeSummariesCompanion data) {
    return HomeSummary(
      id: data.id.present ? data.id.value : this.id,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('HomeSummary(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, payloadJson, cachedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is HomeSummary &&
          other.id == this.id &&
          other.payloadJson == this.payloadJson &&
          other.cachedAt == this.cachedAt);
}

class HomeSummariesCompanion extends UpdateCompanion<HomeSummary> {
  final Value<String> id;
  final Value<String> payloadJson;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const HomeSummariesCompanion({
    this.id = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  HomeSummariesCompanion.insert({
    required String id,
    required String payloadJson,
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       payloadJson = Value(payloadJson),
       cachedAt = Value(cachedAt);
  static Insertable<HomeSummary> custom({
    Expression<String>? id,
    Expression<String>? payloadJson,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  HomeSummariesCompanion copyWith({
    Value<String>? id,
    Value<String>? payloadJson,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return HomeSummariesCompanion(
      id: id ?? this.id,
      payloadJson: payloadJson ?? this.payloadJson,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('HomeSummariesCompanion(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $BriefContentsTable extends BriefContents
    with TableInfo<$BriefContentsTable, BriefContent> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $BriefContentsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _cachedAtMeta = const VerificationMeta(
    'cachedAt',
  );
  @override
  late final GeneratedColumn<DateTime> cachedAt = GeneratedColumn<DateTime>(
    'cached_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [id, payloadJson, cachedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'brief_contents';
  @override
  VerificationContext validateIntegrity(
    Insertable<BriefContent> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_payloadJsonMeta);
    }
    if (data.containsKey('cached_at')) {
      context.handle(
        _cachedAtMeta,
        cachedAt.isAcceptableOrUnknown(data['cached_at']!, _cachedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_cachedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  BriefContent map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return BriefContent(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      )!,
      cachedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}cached_at'],
      )!,
    );
  }

  @override
  $BriefContentsTable createAlias(String alias) {
    return $BriefContentsTable(attachedDatabase, alias);
  }
}

class BriefContent extends DataClass implements Insertable<BriefContent> {
  final String id;
  final String payloadJson;
  final DateTime cachedAt;
  const BriefContent({
    required this.id,
    required this.payloadJson,
    required this.cachedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['payload_json'] = Variable<String>(payloadJson);
    map['cached_at'] = Variable<DateTime>(cachedAt);
    return map;
  }

  BriefContentsCompanion toCompanion(bool nullToAbsent) {
    return BriefContentsCompanion(
      id: Value(id),
      payloadJson: Value(payloadJson),
      cachedAt: Value(cachedAt),
    );
  }

  factory BriefContent.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return BriefContent(
      id: serializer.fromJson<String>(json['id']),
      payloadJson: serializer.fromJson<String>(json['payloadJson']),
      cachedAt: serializer.fromJson<DateTime>(json['cachedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'payloadJson': serializer.toJson<String>(payloadJson),
      'cachedAt': serializer.toJson<DateTime>(cachedAt),
    };
  }

  BriefContent copyWith({
    String? id,
    String? payloadJson,
    DateTime? cachedAt,
  }) => BriefContent(
    id: id ?? this.id,
    payloadJson: payloadJson ?? this.payloadJson,
    cachedAt: cachedAt ?? this.cachedAt,
  );
  BriefContent copyWithCompanion(BriefContentsCompanion data) {
    return BriefContent(
      id: data.id.present ? data.id.value : this.id,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      cachedAt: data.cachedAt.present ? data.cachedAt.value : this.cachedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('BriefContent(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('cachedAt: $cachedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, payloadJson, cachedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is BriefContent &&
          other.id == this.id &&
          other.payloadJson == this.payloadJson &&
          other.cachedAt == this.cachedAt);
}

class BriefContentsCompanion extends UpdateCompanion<BriefContent> {
  final Value<String> id;
  final Value<String> payloadJson;
  final Value<DateTime> cachedAt;
  final Value<int> rowid;
  const BriefContentsCompanion({
    this.id = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.cachedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  BriefContentsCompanion.insert({
    required String id,
    required String payloadJson,
    required DateTime cachedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       payloadJson = Value(payloadJson),
       cachedAt = Value(cachedAt);
  static Insertable<BriefContent> custom({
    Expression<String>? id,
    Expression<String>? payloadJson,
    Expression<DateTime>? cachedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (cachedAt != null) 'cached_at': cachedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  BriefContentsCompanion copyWith({
    Value<String>? id,
    Value<String>? payloadJson,
    Value<DateTime>? cachedAt,
    Value<int>? rowid,
  }) {
    return BriefContentsCompanion(
      id: id ?? this.id,
      payloadJson: payloadJson ?? this.payloadJson,
      cachedAt: cachedAt ?? this.cachedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (cachedAt.present) {
      map['cached_at'] = Variable<DateTime>(cachedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('BriefContentsCompanion(')
          ..write('id: $id, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('cachedAt: $cachedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $RetryOpsTable extends RetryOps with TableInfo<$RetryOpsTable, RetryOp> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $RetryOpsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _kindMeta = const VerificationMeta('kind');
  @override
  late final GeneratedColumn<String> kind = GeneratedColumn<String>(
    'kind',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _endpointMeta = const VerificationMeta(
    'endpoint',
  );
  @override
  late final GeneratedColumn<String> endpoint = GeneratedColumn<String>(
    'endpoint',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
    'status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _errorKindMeta = const VerificationMeta(
    'errorKind',
  );
  @override
  late final GeneratedColumn<String> errorKind = GeneratedColumn<String>(
    'error_kind',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _failedAtMeta = const VerificationMeta(
    'failedAt',
  );
  @override
  late final GeneratedColumn<DateTime> failedAt = GeneratedColumn<DateTime>(
    'failed_at',
    aliasedName,
    false,
    type: DriftSqlType.dateTime,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    id,
    kind,
    endpoint,
    payloadJson,
    status,
    errorKind,
    failedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'retry_ops';
  @override
  VerificationContext validateIntegrity(
    Insertable<RetryOp> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('kind')) {
      context.handle(
        _kindMeta,
        kind.isAcceptableOrUnknown(data['kind']!, _kindMeta),
      );
    } else if (isInserting) {
      context.missing(_kindMeta);
    }
    if (data.containsKey('endpoint')) {
      context.handle(
        _endpointMeta,
        endpoint.isAcceptableOrUnknown(data['endpoint']!, _endpointMeta),
      );
    } else if (isInserting) {
      context.missing(_endpointMeta);
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    }
    if (data.containsKey('status')) {
      context.handle(
        _statusMeta,
        status.isAcceptableOrUnknown(data['status']!, _statusMeta),
      );
    } else if (isInserting) {
      context.missing(_statusMeta);
    }
    if (data.containsKey('error_kind')) {
      context.handle(
        _errorKindMeta,
        errorKind.isAcceptableOrUnknown(data['error_kind']!, _errorKindMeta),
      );
    }
    if (data.containsKey('failed_at')) {
      context.handle(
        _failedAtMeta,
        failedAt.isAcceptableOrUnknown(data['failed_at']!, _failedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_failedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  RetryOp map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return RetryOp(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}id'],
      )!,
      kind: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}kind'],
      )!,
      endpoint: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}endpoint'],
      )!,
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      ),
      status: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}status'],
      )!,
      errorKind: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}error_kind'],
      ),
      failedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.dateTime,
        data['${effectivePrefix}failed_at'],
      )!,
    );
  }

  @override
  $RetryOpsTable createAlias(String alias) {
    return $RetryOpsTable(attachedDatabase, alias);
  }
}

class RetryOp extends DataClass implements Insertable<RetryOp> {
  final String id;
  final String kind;
  final String endpoint;
  final String? payloadJson;
  final String status;
  final String? errorKind;
  final DateTime failedAt;
  const RetryOp({
    required this.id,
    required this.kind,
    required this.endpoint,
    this.payloadJson,
    required this.status,
    this.errorKind,
    required this.failedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['kind'] = Variable<String>(kind);
    map['endpoint'] = Variable<String>(endpoint);
    if (!nullToAbsent || payloadJson != null) {
      map['payload_json'] = Variable<String>(payloadJson);
    }
    map['status'] = Variable<String>(status);
    if (!nullToAbsent || errorKind != null) {
      map['error_kind'] = Variable<String>(errorKind);
    }
    map['failed_at'] = Variable<DateTime>(failedAt);
    return map;
  }

  RetryOpsCompanion toCompanion(bool nullToAbsent) {
    return RetryOpsCompanion(
      id: Value(id),
      kind: Value(kind),
      endpoint: Value(endpoint),
      payloadJson: payloadJson == null && nullToAbsent
          ? const Value.absent()
          : Value(payloadJson),
      status: Value(status),
      errorKind: errorKind == null && nullToAbsent
          ? const Value.absent()
          : Value(errorKind),
      failedAt: Value(failedAt),
    );
  }

  factory RetryOp.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return RetryOp(
      id: serializer.fromJson<String>(json['id']),
      kind: serializer.fromJson<String>(json['kind']),
      endpoint: serializer.fromJson<String>(json['endpoint']),
      payloadJson: serializer.fromJson<String?>(json['payloadJson']),
      status: serializer.fromJson<String>(json['status']),
      errorKind: serializer.fromJson<String?>(json['errorKind']),
      failedAt: serializer.fromJson<DateTime>(json['failedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'kind': serializer.toJson<String>(kind),
      'endpoint': serializer.toJson<String>(endpoint),
      'payloadJson': serializer.toJson<String?>(payloadJson),
      'status': serializer.toJson<String>(status),
      'errorKind': serializer.toJson<String?>(errorKind),
      'failedAt': serializer.toJson<DateTime>(failedAt),
    };
  }

  RetryOp copyWith({
    String? id,
    String? kind,
    String? endpoint,
    Value<String?> payloadJson = const Value.absent(),
    String? status,
    Value<String?> errorKind = const Value.absent(),
    DateTime? failedAt,
  }) => RetryOp(
    id: id ?? this.id,
    kind: kind ?? this.kind,
    endpoint: endpoint ?? this.endpoint,
    payloadJson: payloadJson.present ? payloadJson.value : this.payloadJson,
    status: status ?? this.status,
    errorKind: errorKind.present ? errorKind.value : this.errorKind,
    failedAt: failedAt ?? this.failedAt,
  );
  RetryOp copyWithCompanion(RetryOpsCompanion data) {
    return RetryOp(
      id: data.id.present ? data.id.value : this.id,
      kind: data.kind.present ? data.kind.value : this.kind,
      endpoint: data.endpoint.present ? data.endpoint.value : this.endpoint,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      status: data.status.present ? data.status.value : this.status,
      errorKind: data.errorKind.present ? data.errorKind.value : this.errorKind,
      failedAt: data.failedAt.present ? data.failedAt.value : this.failedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('RetryOp(')
          ..write('id: $id, ')
          ..write('kind: $kind, ')
          ..write('endpoint: $endpoint, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('status: $status, ')
          ..write('errorKind: $errorKind, ')
          ..write('failedAt: $failedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode =>
      Object.hash(id, kind, endpoint, payloadJson, status, errorKind, failedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is RetryOp &&
          other.id == this.id &&
          other.kind == this.kind &&
          other.endpoint == this.endpoint &&
          other.payloadJson == this.payloadJson &&
          other.status == this.status &&
          other.errorKind == this.errorKind &&
          other.failedAt == this.failedAt);
}

class RetryOpsCompanion extends UpdateCompanion<RetryOp> {
  final Value<String> id;
  final Value<String> kind;
  final Value<String> endpoint;
  final Value<String?> payloadJson;
  final Value<String> status;
  final Value<String?> errorKind;
  final Value<DateTime> failedAt;
  final Value<int> rowid;
  const RetryOpsCompanion({
    this.id = const Value.absent(),
    this.kind = const Value.absent(),
    this.endpoint = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.status = const Value.absent(),
    this.errorKind = const Value.absent(),
    this.failedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  RetryOpsCompanion.insert({
    required String id,
    required String kind,
    required String endpoint,
    this.payloadJson = const Value.absent(),
    required String status,
    this.errorKind = const Value.absent(),
    required DateTime failedAt,
    this.rowid = const Value.absent(),
  }) : id = Value(id),
       kind = Value(kind),
       endpoint = Value(endpoint),
       status = Value(status),
       failedAt = Value(failedAt);
  static Insertable<RetryOp> custom({
    Expression<String>? id,
    Expression<String>? kind,
    Expression<String>? endpoint,
    Expression<String>? payloadJson,
    Expression<String>? status,
    Expression<String>? errorKind,
    Expression<DateTime>? failedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (kind != null) 'kind': kind,
      if (endpoint != null) 'endpoint': endpoint,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (status != null) 'status': status,
      if (errorKind != null) 'error_kind': errorKind,
      if (failedAt != null) 'failed_at': failedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  RetryOpsCompanion copyWith({
    Value<String>? id,
    Value<String>? kind,
    Value<String>? endpoint,
    Value<String?>? payloadJson,
    Value<String>? status,
    Value<String?>? errorKind,
    Value<DateTime>? failedAt,
    Value<int>? rowid,
  }) {
    return RetryOpsCompanion(
      id: id ?? this.id,
      kind: kind ?? this.kind,
      endpoint: endpoint ?? this.endpoint,
      payloadJson: payloadJson ?? this.payloadJson,
      status: status ?? this.status,
      errorKind: errorKind ?? this.errorKind,
      failedAt: failedAt ?? this.failedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (kind.present) {
      map['kind'] = Variable<String>(kind.value);
    }
    if (endpoint.present) {
      map['endpoint'] = Variable<String>(endpoint.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (errorKind.present) {
      map['error_kind'] = Variable<String>(errorKind.value);
    }
    if (failedAt.present) {
      map['failed_at'] = Variable<DateTime>(failedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('RetryOpsCompanion(')
          ..write('id: $id, ')
          ..write('kind: $kind, ')
          ..write('endpoint: $endpoint, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('status: $status, ')
          ..write('errorKind: $errorKind, ')
          ..write('failedAt: $failedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

abstract class _$AppCacheDb extends GeneratedDatabase {
  _$AppCacheDb(QueryExecutor e) : super(e);
  $AppCacheDbManager get managers => $AppCacheDbManager(this);
  late final $SessionMessagesTable sessionMessages = $SessionMessagesTable(
    this,
  );
  late final $MemoryItemsTable memoryItems = $MemoryItemsTable(this);
  late final $LedgerSummariesTable ledgerSummaries = $LedgerSummariesTable(
    this,
  );
  late final $LedgerEntriesTable ledgerEntries = $LedgerEntriesTable(this);
  late final $HomeSummariesTable homeSummaries = $HomeSummariesTable(this);
  late final $BriefContentsTable briefContents = $BriefContentsTable(this);
  late final $RetryOpsTable retryOps = $RetryOpsTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [
    sessionMessages,
    memoryItems,
    ledgerSummaries,
    ledgerEntries,
    homeSummaries,
    briefContents,
    retryOps,
  ];
}

typedef $$SessionMessagesTableCreateCompanionBuilder =
    SessionMessagesCompanion Function({
      required String conversationId,
      required String messageId,
      required String role,
      required String content,
      required DateTime eventTime,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$SessionMessagesTableUpdateCompanionBuilder =
    SessionMessagesCompanion Function({
      Value<String> conversationId,
      Value<String> messageId,
      Value<String> role,
      Value<String> content,
      Value<DateTime> eventTime,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$SessionMessagesTableFilterComposer
    extends Composer<_$AppCacheDb, $SessionMessagesTable> {
  $$SessionMessagesTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get conversationId => $composableBuilder(
    column: $table.conversationId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get messageId => $composableBuilder(
    column: $table.messageId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get role => $composableBuilder(
    column: $table.role,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get content => $composableBuilder(
    column: $table.content,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get eventTime => $composableBuilder(
    column: $table.eventTime,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$SessionMessagesTableOrderingComposer
    extends Composer<_$AppCacheDb, $SessionMessagesTable> {
  $$SessionMessagesTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get conversationId => $composableBuilder(
    column: $table.conversationId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get messageId => $composableBuilder(
    column: $table.messageId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get role => $composableBuilder(
    column: $table.role,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get content => $composableBuilder(
    column: $table.content,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get eventTime => $composableBuilder(
    column: $table.eventTime,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$SessionMessagesTableAnnotationComposer
    extends Composer<_$AppCacheDb, $SessionMessagesTable> {
  $$SessionMessagesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get conversationId => $composableBuilder(
    column: $table.conversationId,
    builder: (column) => column,
  );

  GeneratedColumn<String> get messageId =>
      $composableBuilder(column: $table.messageId, builder: (column) => column);

  GeneratedColumn<String> get role =>
      $composableBuilder(column: $table.role, builder: (column) => column);

  GeneratedColumn<String> get content =>
      $composableBuilder(column: $table.content, builder: (column) => column);

  GeneratedColumn<DateTime> get eventTime =>
      $composableBuilder(column: $table.eventTime, builder: (column) => column);

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$SessionMessagesTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $SessionMessagesTable,
          SessionMessage,
          $$SessionMessagesTableFilterComposer,
          $$SessionMessagesTableOrderingComposer,
          $$SessionMessagesTableAnnotationComposer,
          $$SessionMessagesTableCreateCompanionBuilder,
          $$SessionMessagesTableUpdateCompanionBuilder,
          (
            SessionMessage,
            BaseReferences<_$AppCacheDb, $SessionMessagesTable, SessionMessage>,
          ),
          SessionMessage,
          PrefetchHooks Function()
        > {
  $$SessionMessagesTableTableManager(
    _$AppCacheDb db,
    $SessionMessagesTable table,
  ) : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$SessionMessagesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$SessionMessagesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$SessionMessagesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> conversationId = const Value.absent(),
                Value<String> messageId = const Value.absent(),
                Value<String> role = const Value.absent(),
                Value<String> content = const Value.absent(),
                Value<DateTime> eventTime = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => SessionMessagesCompanion(
                conversationId: conversationId,
                messageId: messageId,
                role: role,
                content: content,
                eventTime: eventTime,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String conversationId,
                required String messageId,
                required String role,
                required String content,
                required DateTime eventTime,
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => SessionMessagesCompanion.insert(
                conversationId: conversationId,
                messageId: messageId,
                role: role,
                content: content,
                eventTime: eventTime,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$SessionMessagesTable, SessionMessage>(table),
                  BaseReferences<
                    _$AppCacheDb,
                    $SessionMessagesTable,
                    SessionMessage
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$SessionMessagesTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $SessionMessagesTable,
      SessionMessage,
      $$SessionMessagesTableFilterComposer,
      $$SessionMessagesTableOrderingComposer,
      $$SessionMessagesTableAnnotationComposer,
      $$SessionMessagesTableCreateCompanionBuilder,
      $$SessionMessagesTableUpdateCompanionBuilder,
      (
        SessionMessage,
        BaseReferences<_$AppCacheDb, $SessionMessagesTable, SessionMessage>,
      ),
      SessionMessage,
      PrefetchHooks Function()
    >;
typedef $$MemoryItemsTableCreateCompanionBuilder =
    MemoryItemsCompanion Function({
      required String id,
      required String kind,
      required String label,
      required String content,
      Value<String?> sourceSummary,
      Value<DateTime?> lastUpdated,
      Value<String?> usageReceiptsJson,
      Value<bool> active,
      Value<bool> forgotten,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$MemoryItemsTableUpdateCompanionBuilder =
    MemoryItemsCompanion Function({
      Value<String> id,
      Value<String> kind,
      Value<String> label,
      Value<String> content,
      Value<String?> sourceSummary,
      Value<DateTime?> lastUpdated,
      Value<String?> usageReceiptsJson,
      Value<bool> active,
      Value<bool> forgotten,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$MemoryItemsTableFilterComposer
    extends Composer<_$AppCacheDb, $MemoryItemsTable> {
  $$MemoryItemsTableFilterComposer({
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

  ColumnFilters<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get label => $composableBuilder(
    column: $table.label,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get content => $composableBuilder(
    column: $table.content,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get sourceSummary => $composableBuilder(
    column: $table.sourceSummary,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get lastUpdated => $composableBuilder(
    column: $table.lastUpdated,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get usageReceiptsJson => $composableBuilder(
    column: $table.usageReceiptsJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<bool> get active => $composableBuilder(
    column: $table.active,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<bool> get forgotten => $composableBuilder(
    column: $table.forgotten,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$MemoryItemsTableOrderingComposer
    extends Composer<_$AppCacheDb, $MemoryItemsTable> {
  $$MemoryItemsTableOrderingComposer({
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

  ColumnOrderings<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get label => $composableBuilder(
    column: $table.label,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get content => $composableBuilder(
    column: $table.content,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get sourceSummary => $composableBuilder(
    column: $table.sourceSummary,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get lastUpdated => $composableBuilder(
    column: $table.lastUpdated,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get usageReceiptsJson => $composableBuilder(
    column: $table.usageReceiptsJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<bool> get active => $composableBuilder(
    column: $table.active,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<bool> get forgotten => $composableBuilder(
    column: $table.forgotten,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$MemoryItemsTableAnnotationComposer
    extends Composer<_$AppCacheDb, $MemoryItemsTable> {
  $$MemoryItemsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get kind =>
      $composableBuilder(column: $table.kind, builder: (column) => column);

  GeneratedColumn<String> get label =>
      $composableBuilder(column: $table.label, builder: (column) => column);

  GeneratedColumn<String> get content =>
      $composableBuilder(column: $table.content, builder: (column) => column);

  GeneratedColumn<String> get sourceSummary => $composableBuilder(
    column: $table.sourceSummary,
    builder: (column) => column,
  );

  GeneratedColumn<DateTime> get lastUpdated => $composableBuilder(
    column: $table.lastUpdated,
    builder: (column) => column,
  );

  GeneratedColumn<String> get usageReceiptsJson => $composableBuilder(
    column: $table.usageReceiptsJson,
    builder: (column) => column,
  );

  GeneratedColumn<bool> get active =>
      $composableBuilder(column: $table.active, builder: (column) => column);

  GeneratedColumn<bool> get forgotten =>
      $composableBuilder(column: $table.forgotten, builder: (column) => column);

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$MemoryItemsTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $MemoryItemsTable,
          MemoryItem,
          $$MemoryItemsTableFilterComposer,
          $$MemoryItemsTableOrderingComposer,
          $$MemoryItemsTableAnnotationComposer,
          $$MemoryItemsTableCreateCompanionBuilder,
          $$MemoryItemsTableUpdateCompanionBuilder,
          (
            MemoryItem,
            BaseReferences<_$AppCacheDb, $MemoryItemsTable, MemoryItem>,
          ),
          MemoryItem,
          PrefetchHooks Function()
        > {
  $$MemoryItemsTableTableManager(_$AppCacheDb db, $MemoryItemsTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$MemoryItemsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$MemoryItemsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$MemoryItemsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> kind = const Value.absent(),
                Value<String> label = const Value.absent(),
                Value<String> content = const Value.absent(),
                Value<String?> sourceSummary = const Value.absent(),
                Value<DateTime?> lastUpdated = const Value.absent(),
                Value<String?> usageReceiptsJson = const Value.absent(),
                Value<bool> active = const Value.absent(),
                Value<bool> forgotten = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => MemoryItemsCompanion(
                id: id,
                kind: kind,
                label: label,
                content: content,
                sourceSummary: sourceSummary,
                lastUpdated: lastUpdated,
                usageReceiptsJson: usageReceiptsJson,
                active: active,
                forgotten: forgotten,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String kind,
                required String label,
                required String content,
                Value<String?> sourceSummary = const Value.absent(),
                Value<DateTime?> lastUpdated = const Value.absent(),
                Value<String?> usageReceiptsJson = const Value.absent(),
                Value<bool> active = const Value.absent(),
                Value<bool> forgotten = const Value.absent(),
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => MemoryItemsCompanion.insert(
                id: id,
                kind: kind,
                label: label,
                content: content,
                sourceSummary: sourceSummary,
                lastUpdated: lastUpdated,
                usageReceiptsJson: usageReceiptsJson,
                active: active,
                forgotten: forgotten,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$MemoryItemsTable, MemoryItem>(table),
                  BaseReferences<_$AppCacheDb, $MemoryItemsTable, MemoryItem>(
                    db,
                    table,
                    e,
                  ),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$MemoryItemsTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $MemoryItemsTable,
      MemoryItem,
      $$MemoryItemsTableFilterComposer,
      $$MemoryItemsTableOrderingComposer,
      $$MemoryItemsTableAnnotationComposer,
      $$MemoryItemsTableCreateCompanionBuilder,
      $$MemoryItemsTableUpdateCompanionBuilder,
      (MemoryItem, BaseReferences<_$AppCacheDb, $MemoryItemsTable, MemoryItem>),
      MemoryItem,
      PrefetchHooks Function()
    >;
typedef $$LedgerSummariesTableCreateCompanionBuilder =
    LedgerSummariesCompanion Function({
      required String id,
      required String payloadJson,
      Value<String?> formattedAmount,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$LedgerSummariesTableUpdateCompanionBuilder =
    LedgerSummariesCompanion Function({
      Value<String> id,
      Value<String> payloadJson,
      Value<String?> formattedAmount,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$LedgerSummariesTableFilterComposer
    extends Composer<_$AppCacheDb, $LedgerSummariesTable> {
  $$LedgerSummariesTableFilterComposer({
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

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$LedgerSummariesTableOrderingComposer
    extends Composer<_$AppCacheDb, $LedgerSummariesTable> {
  $$LedgerSummariesTableOrderingComposer({
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

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$LedgerSummariesTableAnnotationComposer
    extends Composer<_$AppCacheDb, $LedgerSummariesTable> {
  $$LedgerSummariesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => column,
  );

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$LedgerSummariesTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $LedgerSummariesTable,
          LedgerSummary,
          $$LedgerSummariesTableFilterComposer,
          $$LedgerSummariesTableOrderingComposer,
          $$LedgerSummariesTableAnnotationComposer,
          $$LedgerSummariesTableCreateCompanionBuilder,
          $$LedgerSummariesTableUpdateCompanionBuilder,
          (
            LedgerSummary,
            BaseReferences<_$AppCacheDb, $LedgerSummariesTable, LedgerSummary>,
          ),
          LedgerSummary,
          PrefetchHooks Function()
        > {
  $$LedgerSummariesTableTableManager(
    _$AppCacheDb db,
    $LedgerSummariesTable table,
  ) : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$LedgerSummariesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$LedgerSummariesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$LedgerSummariesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> payloadJson = const Value.absent(),
                Value<String?> formattedAmount = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => LedgerSummariesCompanion(
                id: id,
                payloadJson: payloadJson,
                formattedAmount: formattedAmount,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String payloadJson,
                Value<String?> formattedAmount = const Value.absent(),
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => LedgerSummariesCompanion.insert(
                id: id,
                payloadJson: payloadJson,
                formattedAmount: formattedAmount,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$LedgerSummariesTable, LedgerSummary>(table),
                  BaseReferences<
                    _$AppCacheDb,
                    $LedgerSummariesTable,
                    LedgerSummary
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$LedgerSummariesTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $LedgerSummariesTable,
      LedgerSummary,
      $$LedgerSummariesTableFilterComposer,
      $$LedgerSummariesTableOrderingComposer,
      $$LedgerSummariesTableAnnotationComposer,
      $$LedgerSummariesTableCreateCompanionBuilder,
      $$LedgerSummariesTableUpdateCompanionBuilder,
      (
        LedgerSummary,
        BaseReferences<_$AppCacheDb, $LedgerSummariesTable, LedgerSummary>,
      ),
      LedgerSummary,
      PrefetchHooks Function()
    >;
typedef $$LedgerEntriesTableCreateCompanionBuilder =
    LedgerEntriesCompanion Function({
      required String id,
      required String title,
      required String formattedAmount,
      Value<String?> source,
      Value<DateTime?> eventTime,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$LedgerEntriesTableUpdateCompanionBuilder =
    LedgerEntriesCompanion Function({
      Value<String> id,
      Value<String> title,
      Value<String> formattedAmount,
      Value<String?> source,
      Value<DateTime?> eventTime,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$LedgerEntriesTableFilterComposer
    extends Composer<_$AppCacheDb, $LedgerEntriesTable> {
  $$LedgerEntriesTableFilterComposer({
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

  ColumnFilters<String> get title => $composableBuilder(
    column: $table.title,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get source => $composableBuilder(
    column: $table.source,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get eventTime => $composableBuilder(
    column: $table.eventTime,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$LedgerEntriesTableOrderingComposer
    extends Composer<_$AppCacheDb, $LedgerEntriesTable> {
  $$LedgerEntriesTableOrderingComposer({
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

  ColumnOrderings<String> get title => $composableBuilder(
    column: $table.title,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get source => $composableBuilder(
    column: $table.source,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get eventTime => $composableBuilder(
    column: $table.eventTime,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$LedgerEntriesTableAnnotationComposer
    extends Composer<_$AppCacheDb, $LedgerEntriesTable> {
  $$LedgerEntriesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get title =>
      $composableBuilder(column: $table.title, builder: (column) => column);

  GeneratedColumn<String> get formattedAmount => $composableBuilder(
    column: $table.formattedAmount,
    builder: (column) => column,
  );

  GeneratedColumn<String> get source =>
      $composableBuilder(column: $table.source, builder: (column) => column);

  GeneratedColumn<DateTime> get eventTime =>
      $composableBuilder(column: $table.eventTime, builder: (column) => column);

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$LedgerEntriesTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $LedgerEntriesTable,
          LedgerEntry,
          $$LedgerEntriesTableFilterComposer,
          $$LedgerEntriesTableOrderingComposer,
          $$LedgerEntriesTableAnnotationComposer,
          $$LedgerEntriesTableCreateCompanionBuilder,
          $$LedgerEntriesTableUpdateCompanionBuilder,
          (
            LedgerEntry,
            BaseReferences<_$AppCacheDb, $LedgerEntriesTable, LedgerEntry>,
          ),
          LedgerEntry,
          PrefetchHooks Function()
        > {
  $$LedgerEntriesTableTableManager(_$AppCacheDb db, $LedgerEntriesTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$LedgerEntriesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$LedgerEntriesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$LedgerEntriesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> title = const Value.absent(),
                Value<String> formattedAmount = const Value.absent(),
                Value<String?> source = const Value.absent(),
                Value<DateTime?> eventTime = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => LedgerEntriesCompanion(
                id: id,
                title: title,
                formattedAmount: formattedAmount,
                source: source,
                eventTime: eventTime,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String title,
                required String formattedAmount,
                Value<String?> source = const Value.absent(),
                Value<DateTime?> eventTime = const Value.absent(),
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => LedgerEntriesCompanion.insert(
                id: id,
                title: title,
                formattedAmount: formattedAmount,
                source: source,
                eventTime: eventTime,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$LedgerEntriesTable, LedgerEntry>(table),
                  BaseReferences<
                    _$AppCacheDb,
                    $LedgerEntriesTable,
                    LedgerEntry
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$LedgerEntriesTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $LedgerEntriesTable,
      LedgerEntry,
      $$LedgerEntriesTableFilterComposer,
      $$LedgerEntriesTableOrderingComposer,
      $$LedgerEntriesTableAnnotationComposer,
      $$LedgerEntriesTableCreateCompanionBuilder,
      $$LedgerEntriesTableUpdateCompanionBuilder,
      (
        LedgerEntry,
        BaseReferences<_$AppCacheDb, $LedgerEntriesTable, LedgerEntry>,
      ),
      LedgerEntry,
      PrefetchHooks Function()
    >;
typedef $$HomeSummariesTableCreateCompanionBuilder =
    HomeSummariesCompanion Function({
      required String id,
      required String payloadJson,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$HomeSummariesTableUpdateCompanionBuilder =
    HomeSummariesCompanion Function({
      Value<String> id,
      Value<String> payloadJson,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$HomeSummariesTableFilterComposer
    extends Composer<_$AppCacheDb, $HomeSummariesTable> {
  $$HomeSummariesTableFilterComposer({
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

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$HomeSummariesTableOrderingComposer
    extends Composer<_$AppCacheDb, $HomeSummariesTable> {
  $$HomeSummariesTableOrderingComposer({
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

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$HomeSummariesTableAnnotationComposer
    extends Composer<_$AppCacheDb, $HomeSummariesTable> {
  $$HomeSummariesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$HomeSummariesTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $HomeSummariesTable,
          HomeSummary,
          $$HomeSummariesTableFilterComposer,
          $$HomeSummariesTableOrderingComposer,
          $$HomeSummariesTableAnnotationComposer,
          $$HomeSummariesTableCreateCompanionBuilder,
          $$HomeSummariesTableUpdateCompanionBuilder,
          (
            HomeSummary,
            BaseReferences<_$AppCacheDb, $HomeSummariesTable, HomeSummary>,
          ),
          HomeSummary,
          PrefetchHooks Function()
        > {
  $$HomeSummariesTableTableManager(_$AppCacheDb db, $HomeSummariesTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$HomeSummariesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$HomeSummariesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$HomeSummariesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> payloadJson = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => HomeSummariesCompanion(
                id: id,
                payloadJson: payloadJson,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String payloadJson,
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => HomeSummariesCompanion.insert(
                id: id,
                payloadJson: payloadJson,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$HomeSummariesTable, HomeSummary>(table),
                  BaseReferences<
                    _$AppCacheDb,
                    $HomeSummariesTable,
                    HomeSummary
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$HomeSummariesTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $HomeSummariesTable,
      HomeSummary,
      $$HomeSummariesTableFilterComposer,
      $$HomeSummariesTableOrderingComposer,
      $$HomeSummariesTableAnnotationComposer,
      $$HomeSummariesTableCreateCompanionBuilder,
      $$HomeSummariesTableUpdateCompanionBuilder,
      (
        HomeSummary,
        BaseReferences<_$AppCacheDb, $HomeSummariesTable, HomeSummary>,
      ),
      HomeSummary,
      PrefetchHooks Function()
    >;
typedef $$BriefContentsTableCreateCompanionBuilder =
    BriefContentsCompanion Function({
      required String id,
      required String payloadJson,
      required DateTime cachedAt,
      Value<int> rowid,
    });
typedef $$BriefContentsTableUpdateCompanionBuilder =
    BriefContentsCompanion Function({
      Value<String> id,
      Value<String> payloadJson,
      Value<DateTime> cachedAt,
      Value<int> rowid,
    });

class $$BriefContentsTableFilterComposer
    extends Composer<_$AppCacheDb, $BriefContentsTable> {
  $$BriefContentsTableFilterComposer({
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

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$BriefContentsTableOrderingComposer
    extends Composer<_$AppCacheDb, $BriefContentsTable> {
  $$BriefContentsTableOrderingComposer({
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

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get cachedAt => $composableBuilder(
    column: $table.cachedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$BriefContentsTableAnnotationComposer
    extends Composer<_$AppCacheDb, $BriefContentsTable> {
  $$BriefContentsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<DateTime> get cachedAt =>
      $composableBuilder(column: $table.cachedAt, builder: (column) => column);
}

class $$BriefContentsTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $BriefContentsTable,
          BriefContent,
          $$BriefContentsTableFilterComposer,
          $$BriefContentsTableOrderingComposer,
          $$BriefContentsTableAnnotationComposer,
          $$BriefContentsTableCreateCompanionBuilder,
          $$BriefContentsTableUpdateCompanionBuilder,
          (
            BriefContent,
            BaseReferences<_$AppCacheDb, $BriefContentsTable, BriefContent>,
          ),
          BriefContent,
          PrefetchHooks Function()
        > {
  $$BriefContentsTableTableManager(_$AppCacheDb db, $BriefContentsTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$BriefContentsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$BriefContentsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$BriefContentsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> payloadJson = const Value.absent(),
                Value<DateTime> cachedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => BriefContentsCompanion(
                id: id,
                payloadJson: payloadJson,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String payloadJson,
                required DateTime cachedAt,
                Value<int> rowid = const Value.absent(),
              }) => BriefContentsCompanion.insert(
                id: id,
                payloadJson: payloadJson,
                cachedAt: cachedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$BriefContentsTable, BriefContent>(table),
                  BaseReferences<
                    _$AppCacheDb,
                    $BriefContentsTable,
                    BriefContent
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$BriefContentsTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $BriefContentsTable,
      BriefContent,
      $$BriefContentsTableFilterComposer,
      $$BriefContentsTableOrderingComposer,
      $$BriefContentsTableAnnotationComposer,
      $$BriefContentsTableCreateCompanionBuilder,
      $$BriefContentsTableUpdateCompanionBuilder,
      (
        BriefContent,
        BaseReferences<_$AppCacheDb, $BriefContentsTable, BriefContent>,
      ),
      BriefContent,
      PrefetchHooks Function()
    >;
typedef $$RetryOpsTableCreateCompanionBuilder = RetryOpsCompanion Function({
  required String id,
  required String kind,
  required String endpoint,
  Value<String?> payloadJson,
  required String status,
  Value<String?> errorKind,
  required DateTime failedAt,
  Value<int> rowid,
});
typedef $$RetryOpsTableUpdateCompanionBuilder = RetryOpsCompanion Function({
  Value<String> id,
  Value<String> kind,
  Value<String> endpoint,
  Value<String?> payloadJson,
  Value<String> status,
  Value<String?> errorKind,
  Value<DateTime> failedAt,
  Value<int> rowid,
});

class $$RetryOpsTableFilterComposer
    extends Composer<_$AppCacheDb, $RetryOpsTable> {
  $$RetryOpsTableFilterComposer({
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

  ColumnFilters<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get endpoint => $composableBuilder(
    column: $table.endpoint,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get errorKind => $composableBuilder(
    column: $table.errorKind,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<DateTime> get failedAt => $composableBuilder(
    column: $table.failedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$RetryOpsTableOrderingComposer
    extends Composer<_$AppCacheDb, $RetryOpsTable> {
  $$RetryOpsTableOrderingComposer({
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

  ColumnOrderings<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get endpoint => $composableBuilder(
    column: $table.endpoint,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get errorKind => $composableBuilder(
    column: $table.errorKind,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<DateTime> get failedAt => $composableBuilder(
    column: $table.failedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$RetryOpsTableAnnotationComposer
    extends Composer<_$AppCacheDb, $RetryOpsTable> {
  $$RetryOpsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get kind =>
      $composableBuilder(column: $table.kind, builder: (column) => column);

  GeneratedColumn<String> get endpoint =>
      $composableBuilder(column: $table.endpoint, builder: (column) => column);

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<String> get errorKind =>
      $composableBuilder(column: $table.errorKind, builder: (column) => column);

  GeneratedColumn<DateTime> get failedAt =>
      $composableBuilder(column: $table.failedAt, builder: (column) => column);
}

class $$RetryOpsTableTableManager
    extends
        RootTableManager<
          _$AppCacheDb,
          $RetryOpsTable,
          RetryOp,
          $$RetryOpsTableFilterComposer,
          $$RetryOpsTableOrderingComposer,
          $$RetryOpsTableAnnotationComposer,
          $$RetryOpsTableCreateCompanionBuilder,
          $$RetryOpsTableUpdateCompanionBuilder,
          (RetryOp, BaseReferences<_$AppCacheDb, $RetryOpsTable, RetryOp>),
          RetryOp,
          PrefetchHooks Function()
        > {
  $$RetryOpsTableTableManager(_$AppCacheDb db, $RetryOpsTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$RetryOpsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$RetryOpsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$RetryOpsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> id = const Value.absent(),
                Value<String> kind = const Value.absent(),
                Value<String> endpoint = const Value.absent(),
                Value<String?> payloadJson = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<String?> errorKind = const Value.absent(),
                Value<DateTime> failedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => RetryOpsCompanion(
                id: id,
                kind: kind,
                endpoint: endpoint,
                payloadJson: payloadJson,
                status: status,
                errorKind: errorKind,
                failedAt: failedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String id,
                required String kind,
                required String endpoint,
                Value<String?> payloadJson = const Value.absent(),
                required String status,
                Value<String?> errorKind = const Value.absent(),
                required DateTime failedAt,
                Value<int> rowid = const Value.absent(),
              }) => RetryOpsCompanion.insert(
                id: id,
                kind: kind,
                endpoint: endpoint,
                payloadJson: payloadJson,
                status: status,
                errorKind: errorKind,
                failedAt: failedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$RetryOpsTable, RetryOp>(table),
                  BaseReferences<_$AppCacheDb, $RetryOpsTable, RetryOp>(
                    db,
                    table,
                    e,
                  ),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$RetryOpsTableProcessedTableManager =
    ProcessedTableManager<
      _$AppCacheDb,
      $RetryOpsTable,
      RetryOp,
      $$RetryOpsTableFilterComposer,
      $$RetryOpsTableOrderingComposer,
      $$RetryOpsTableAnnotationComposer,
      $$RetryOpsTableCreateCompanionBuilder,
      $$RetryOpsTableUpdateCompanionBuilder,
      (RetryOp, BaseReferences<_$AppCacheDb, $RetryOpsTable, RetryOp>),
      RetryOp,
      PrefetchHooks Function()
    >;

class $AppCacheDbManager {
  final _$AppCacheDb _db;
  $AppCacheDbManager(this._db);
  $$SessionMessagesTableTableManager get sessionMessages =>
      $$SessionMessagesTableTableManager(_db, _db.sessionMessages);
  $$MemoryItemsTableTableManager get memoryItems =>
      $$MemoryItemsTableTableManager(_db, _db.memoryItems);
  $$LedgerSummariesTableTableManager get ledgerSummaries =>
      $$LedgerSummariesTableTableManager(_db, _db.ledgerSummaries);
  $$LedgerEntriesTableTableManager get ledgerEntries =>
      $$LedgerEntriesTableTableManager(_db, _db.ledgerEntries);
  $$HomeSummariesTableTableManager get homeSummaries =>
      $$HomeSummariesTableTableManager(_db, _db.homeSummaries);
  $$BriefContentsTableTableManager get briefContents =>
      $$BriefContentsTableTableManager(_db, _db.briefContents);
  $$RetryOpsTableTableManager get retryOps =>
      $$RetryOpsTableTableManager(_db, _db.retryOps);
}
