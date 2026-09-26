// GENERATED CODE - DO NOT MODIFY BY HAND
// coverage:ignore-file
// ignore_for_file: type=lint, type=warning, deprecated_member_use, deprecated_member_use_from_same_package
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'chat_event.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

// GENERATED CODE - DO NOT MODIFY BY HAND
// dart format off
T _$identity<T>(T value) => value;
/// @nodoc
mixin _$ChatEvent {





@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is ChatEvent);
}


@override
int get hashCode => runtimeType.hashCode;

@override
String toString() {
  return 'ChatEvent()';
}


}

/// @nodoc
class $ChatEventCopyWith<$Res>  {
$ChatEventCopyWith(ChatEvent _, $Res Function(ChatEvent) __);
}


/// Adds pattern-matching-related methods to [ChatEvent].
extension ChatEventPatterns on ChatEvent {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>({TResult Function( TurnMeta value)?  turnMeta,TResult Function( TokenDelta value)?  token,TResult Function( ReplyReplace value)?  replyReplace,TResult Function( ToolStep value)?  toolStep,TResult Function( Done value)?  done,TResult Function( Failure value)?  failure,required TResult orElse(),}){
final _that = this;
switch (_that) {
case TurnMeta() when turnMeta != null:
return turnMeta(_that);case TokenDelta() when token != null:
return token(_that);case ReplyReplace() when replyReplace != null:
return replyReplace(_that);case ToolStep() when toolStep != null:
return toolStep(_that);case Done() when done != null:
return done(_that);case Failure() when failure != null:
return failure(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>({required TResult Function( TurnMeta value)  turnMeta,required TResult Function( TokenDelta value)  token,required TResult Function( ReplyReplace value)  replyReplace,required TResult Function( ToolStep value)  toolStep,required TResult Function( Done value)  done,required TResult Function( Failure value)  failure,}){
final _that = this;
switch (_that) {
case TurnMeta():
return turnMeta(_that);case TokenDelta():
return token(_that);case ReplyReplace():
return replyReplace(_that);case ToolStep():
return toolStep(_that);case Done():
return done(_that);case Failure():
return failure(_that);}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>({TResult? Function( TurnMeta value)?  turnMeta,TResult? Function( TokenDelta value)?  token,TResult? Function( ReplyReplace value)?  replyReplace,TResult? Function( ToolStep value)?  toolStep,TResult? Function( Done value)?  done,TResult? Function( Failure value)?  failure,}){
final _that = this;
switch (_that) {
case TurnMeta() when turnMeta != null:
return turnMeta(_that);case TokenDelta() when token != null:
return token(_that);case ReplyReplace() when replyReplace != null:
return replyReplace(_that);case ToolStep() when toolStep != null:
return toolStep(_that);case Done() when done != null:
return done(_that);case Failure() when failure != null:
return failure(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>({TResult Function( String? roleMode,  String? analysis,  String? sceneId,  String? sceneLabel,  String? intention,  String? currentGoal,  String? behavior,  String? mode,  String? actionIntent,  MemoryRefs? memoryRefs)?  turnMeta,TResult Function( String delta)?  token,TResult Function( String text)?  replyReplace,TResult Function( String stepId,  String toolId,  String label,  String status,  String? detail,  String? target)?  toolStep,TResult Function()?  done,TResult Function( String? detail,  String? error)?  failure,required TResult orElse(),}) {final _that = this;
switch (_that) {
case TurnMeta() when turnMeta != null:
return turnMeta(_that.roleMode,_that.analysis,_that.sceneId,_that.sceneLabel,_that.intention,_that.currentGoal,_that.behavior,_that.mode,_that.actionIntent,_that.memoryRefs);case TokenDelta() when token != null:
return token(_that.delta);case ReplyReplace() when replyReplace != null:
return replyReplace(_that.text);case ToolStep() when toolStep != null:
return toolStep(_that.stepId,_that.toolId,_that.label,_that.status,_that.detail,_that.target);case Done() when done != null:
return done();case Failure() when failure != null:
return failure(_that.detail,_that.error);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>({required TResult Function( String? roleMode,  String? analysis,  String? sceneId,  String? sceneLabel,  String? intention,  String? currentGoal,  String? behavior,  String? mode,  String? actionIntent,  MemoryRefs? memoryRefs)  turnMeta,required TResult Function( String delta)  token,required TResult Function( String text)  replyReplace,required TResult Function( String stepId,  String toolId,  String label,  String status,  String? detail,  String? target)  toolStep,required TResult Function()  done,required TResult Function( String? detail,  String? error)  failure,}) {final _that = this;
switch (_that) {
case TurnMeta():
return turnMeta(_that.roleMode,_that.analysis,_that.sceneId,_that.sceneLabel,_that.intention,_that.currentGoal,_that.behavior,_that.mode,_that.actionIntent,_that.memoryRefs);case TokenDelta():
return token(_that.delta);case ReplyReplace():
return replyReplace(_that.text);case ToolStep():
return toolStep(_that.stepId,_that.toolId,_that.label,_that.status,_that.detail,_that.target);case Done():
return done();case Failure():
return failure(_that.detail,_that.error);}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>({TResult? Function( String? roleMode,  String? analysis,  String? sceneId,  String? sceneLabel,  String? intention,  String? currentGoal,  String? behavior,  String? mode,  String? actionIntent,  MemoryRefs? memoryRefs)?  turnMeta,TResult? Function( String delta)?  token,TResult? Function( String text)?  replyReplace,TResult? Function( String stepId,  String toolId,  String label,  String status,  String? detail,  String? target)?  toolStep,TResult? Function()?  done,TResult? Function( String? detail,  String? error)?  failure,}) {final _that = this;
switch (_that) {
case TurnMeta() when turnMeta != null:
return turnMeta(_that.roleMode,_that.analysis,_that.sceneId,_that.sceneLabel,_that.intention,_that.currentGoal,_that.behavior,_that.mode,_that.actionIntent,_that.memoryRefs);case TokenDelta() when token != null:
return token(_that.delta);case ReplyReplace() when replyReplace != null:
return replyReplace(_that.text);case ToolStep() when toolStep != null:
return toolStep(_that.stepId,_that.toolId,_that.label,_that.status,_that.detail,_that.target);case Done() when done != null:
return done();case Failure() when failure != null:
return failure(_that.detail,_that.error);case _:
  return null;

}
}

}

/// @nodoc


class TurnMeta implements ChatEvent {
  const TurnMeta({this.roleMode, this.analysis, this.sceneId, this.sceneLabel, this.intention, this.currentGoal, this.behavior, this.mode, this.actionIntent, this.memoryRefs});
  

 final  String? roleMode;
 final  String? analysis;
 final  String? sceneId;
 final  String? sceneLabel;
 final  String? intention;
 final  String? currentGoal;
 final  String? behavior;
 final  String? mode;
 final  String? actionIntent;
 final  MemoryRefs? memoryRefs;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$TurnMetaCopyWith<TurnMeta> get copyWith => _$TurnMetaCopyWithImpl<TurnMeta>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is TurnMeta&&(identical(other.roleMode, roleMode) || other.roleMode == roleMode)&&(identical(other.analysis, analysis) || other.analysis == analysis)&&(identical(other.sceneId, sceneId) || other.sceneId == sceneId)&&(identical(other.sceneLabel, sceneLabel) || other.sceneLabel == sceneLabel)&&(identical(other.intention, intention) || other.intention == intention)&&(identical(other.currentGoal, currentGoal) || other.currentGoal == currentGoal)&&(identical(other.behavior, behavior) || other.behavior == behavior)&&(identical(other.mode, mode) || other.mode == mode)&&(identical(other.actionIntent, actionIntent) || other.actionIntent == actionIntent)&&(identical(other.memoryRefs, memoryRefs) || other.memoryRefs == memoryRefs));
}


@override
int get hashCode => Object.hash(runtimeType,roleMode,analysis,sceneId,sceneLabel,intention,currentGoal,behavior,mode,actionIntent,memoryRefs);

@override
String toString() {
  return 'ChatEvent.turnMeta(roleMode: $roleMode, analysis: $analysis, sceneId: $sceneId, sceneLabel: $sceneLabel, intention: $intention, currentGoal: $currentGoal, behavior: $behavior, mode: $mode, actionIntent: $actionIntent, memoryRefs: $memoryRefs)';
}


}

/// @nodoc
abstract mixin class $TurnMetaCopyWith<$Res> implements $ChatEventCopyWith<$Res> {
  factory $TurnMetaCopyWith(TurnMeta value, $Res Function(TurnMeta) _then) = _$TurnMetaCopyWithImpl;
@useResult
$Res call({
 String? roleMode, String? analysis, String? sceneId, String? sceneLabel, String? intention, String? currentGoal, String? behavior, String? mode, String? actionIntent, MemoryRefs? memoryRefs
});




}
/// @nodoc
class _$TurnMetaCopyWithImpl<$Res>
    implements $TurnMetaCopyWith<$Res> {
  _$TurnMetaCopyWithImpl(this._self, this._then);

  final TurnMeta _self;
  final $Res Function(TurnMeta) _then;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') $Res call({Object? roleMode = freezed,Object? analysis = freezed,Object? sceneId = freezed,Object? sceneLabel = freezed,Object? intention = freezed,Object? currentGoal = freezed,Object? behavior = freezed,Object? mode = freezed,Object? actionIntent = freezed,Object? memoryRefs = freezed,}) {
  return _then(TurnMeta(
roleMode: freezed == roleMode ? _self.roleMode : roleMode // ignore: cast_nullable_to_non_nullable
as String?,analysis: freezed == analysis ? _self.analysis : analysis // ignore: cast_nullable_to_non_nullable
as String?,sceneId: freezed == sceneId ? _self.sceneId : sceneId // ignore: cast_nullable_to_non_nullable
as String?,sceneLabel: freezed == sceneLabel ? _self.sceneLabel : sceneLabel // ignore: cast_nullable_to_non_nullable
as String?,intention: freezed == intention ? _self.intention : intention // ignore: cast_nullable_to_non_nullable
as String?,currentGoal: freezed == currentGoal ? _self.currentGoal : currentGoal // ignore: cast_nullable_to_non_nullable
as String?,behavior: freezed == behavior ? _self.behavior : behavior // ignore: cast_nullable_to_non_nullable
as String?,mode: freezed == mode ? _self.mode : mode // ignore: cast_nullable_to_non_nullable
as String?,actionIntent: freezed == actionIntent ? _self.actionIntent : actionIntent // ignore: cast_nullable_to_non_nullable
as String?,memoryRefs: freezed == memoryRefs ? _self.memoryRefs : memoryRefs // ignore: cast_nullable_to_non_nullable
as MemoryRefs?,
  ));
}


}

/// @nodoc


class TokenDelta implements ChatEvent {
  const TokenDelta({required this.delta});
  

 final  String delta;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$TokenDeltaCopyWith<TokenDelta> get copyWith => _$TokenDeltaCopyWithImpl<TokenDelta>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is TokenDelta&&(identical(other.delta, delta) || other.delta == delta));
}


@override
int get hashCode => Object.hash(runtimeType,delta);

@override
String toString() {
  return 'ChatEvent.token(delta: $delta)';
}


}

/// @nodoc
abstract mixin class $TokenDeltaCopyWith<$Res> implements $ChatEventCopyWith<$Res> {
  factory $TokenDeltaCopyWith(TokenDelta value, $Res Function(TokenDelta) _then) = _$TokenDeltaCopyWithImpl;
@useResult
$Res call({
 String delta
});




}
/// @nodoc
class _$TokenDeltaCopyWithImpl<$Res>
    implements $TokenDeltaCopyWith<$Res> {
  _$TokenDeltaCopyWithImpl(this._self, this._then);

  final TokenDelta _self;
  final $Res Function(TokenDelta) _then;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') $Res call({Object? delta = null,}) {
  return _then(TokenDelta(
delta: null == delta ? _self.delta : delta // ignore: cast_nullable_to_non_nullable
as String,
  ));
}


}

/// @nodoc


class ReplyReplace implements ChatEvent {
  const ReplyReplace({required this.text});
  

 final  String text;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$ReplyReplaceCopyWith<ReplyReplace> get copyWith => _$ReplyReplaceCopyWithImpl<ReplyReplace>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is ReplyReplace&&(identical(other.text, text) || other.text == text));
}


@override
int get hashCode => Object.hash(runtimeType,text);

@override
String toString() {
  return 'ChatEvent.replyReplace(text: $text)';
}


}

/// @nodoc
abstract mixin class $ReplyReplaceCopyWith<$Res> implements $ChatEventCopyWith<$Res> {
  factory $ReplyReplaceCopyWith(ReplyReplace value, $Res Function(ReplyReplace) _then) = _$ReplyReplaceCopyWithImpl;
@useResult
$Res call({
 String text
});




}
/// @nodoc
class _$ReplyReplaceCopyWithImpl<$Res>
    implements $ReplyReplaceCopyWith<$Res> {
  _$ReplyReplaceCopyWithImpl(this._self, this._then);

  final ReplyReplace _self;
  final $Res Function(ReplyReplace) _then;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') $Res call({Object? text = null,}) {
  return _then(ReplyReplace(
text: null == text ? _self.text : text // ignore: cast_nullable_to_non_nullable
as String,
  ));
}


}

/// @nodoc


class ToolStep implements ChatEvent {
  const ToolStep({required this.stepId, required this.toolId, required this.label, required this.status, this.detail, this.target});
  

 final  String stepId;
 final  String toolId;
 final  String label;
 final  String status;
 final  String? detail;
 final  String? target;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$ToolStepCopyWith<ToolStep> get copyWith => _$ToolStepCopyWithImpl<ToolStep>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is ToolStep&&(identical(other.stepId, stepId) || other.stepId == stepId)&&(identical(other.toolId, toolId) || other.toolId == toolId)&&(identical(other.label, label) || other.label == label)&&(identical(other.status, status) || other.status == status)&&(identical(other.detail, detail) || other.detail == detail)&&(identical(other.target, target) || other.target == target));
}


@override
int get hashCode => Object.hash(runtimeType,stepId,toolId,label,status,detail,target);

@override
String toString() {
  return 'ChatEvent.toolStep(stepId: $stepId, toolId: $toolId, label: $label, status: $status, detail: $detail, target: $target)';
}


}

/// @nodoc
abstract mixin class $ToolStepCopyWith<$Res> implements $ChatEventCopyWith<$Res> {
  factory $ToolStepCopyWith(ToolStep value, $Res Function(ToolStep) _then) = _$ToolStepCopyWithImpl;
@useResult
$Res call({
 String stepId, String toolId, String label, String status, String? detail, String? target
});




}
/// @nodoc
class _$ToolStepCopyWithImpl<$Res>
    implements $ToolStepCopyWith<$Res> {
  _$ToolStepCopyWithImpl(this._self, this._then);

  final ToolStep _self;
  final $Res Function(ToolStep) _then;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') $Res call({Object? stepId = null,Object? toolId = null,Object? label = null,Object? status = null,Object? detail = freezed,Object? target = freezed,}) {
  return _then(ToolStep(
stepId: null == stepId ? _self.stepId : stepId // ignore: cast_nullable_to_non_nullable
as String,toolId: null == toolId ? _self.toolId : toolId // ignore: cast_nullable_to_non_nullable
as String,label: null == label ? _self.label : label // ignore: cast_nullable_to_non_nullable
as String,status: null == status ? _self.status : status // ignore: cast_nullable_to_non_nullable
as String,detail: freezed == detail ? _self.detail : detail // ignore: cast_nullable_to_non_nullable
as String?,target: freezed == target ? _self.target : target // ignore: cast_nullable_to_non_nullable
as String?,
  ));
}


}

/// @nodoc


class Done implements ChatEvent {
  const Done();
  






@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is Done);
}


@override
int get hashCode => runtimeType.hashCode;

@override
String toString() {
  return 'ChatEvent.done()';
}


}




/// @nodoc


class Failure implements ChatEvent {
  const Failure({this.detail, this.error});
  

 final  String? detail;
 final  String? error;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$FailureCopyWith<Failure> get copyWith => _$FailureCopyWithImpl<Failure>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is Failure&&(identical(other.detail, detail) || other.detail == detail)&&(identical(other.error, error) || other.error == error));
}


@override
int get hashCode => Object.hash(runtimeType,detail,error);

@override
String toString() {
  return 'ChatEvent.failure(detail: $detail, error: $error)';
}


}

/// @nodoc
abstract mixin class $FailureCopyWith<$Res> implements $ChatEventCopyWith<$Res> {
  factory $FailureCopyWith(Failure value, $Res Function(Failure) _then) = _$FailureCopyWithImpl;
@useResult
$Res call({
 String? detail, String? error
});




}
/// @nodoc
class _$FailureCopyWithImpl<$Res>
    implements $FailureCopyWith<$Res> {
  _$FailureCopyWithImpl(this._self, this._then);

  final Failure _self;
  final $Res Function(Failure) _then;

/// Create a copy of ChatEvent
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') $Res call({Object? detail = freezed,Object? error = freezed,}) {
  return _then(Failure(
detail: freezed == detail ? _self.detail : detail // ignore: cast_nullable_to_non_nullable
as String?,error: freezed == error ? _self.error : error // ignore: cast_nullable_to_non_nullable
as String?,
  ));
}


}

// dart format on
