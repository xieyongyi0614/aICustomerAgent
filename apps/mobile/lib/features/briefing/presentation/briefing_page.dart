import 'package:flutter/material.dart';
import 'package:mobile/app/theme/theme_context.dart';

class BriefingPage extends StatelessWidget {
  const BriefingPage({super.key, this.form = 'morning'});

  /// morning | evening
  final String form;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: context.gradients.deepBrief),
        child: SafeArea(
          child: Center(
            child: Text(
              form == 'evening' ? '晚间总结' : '早间简报',
              style: context.typography.briefTitle
                  .copyWith(color: colors.onDeepPrimary),
            ),
          ),
        ),
      ),
    );
  }
}
