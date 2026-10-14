import React from 'react';
import { StyleProp, Text, TextProps, TextStyle } from 'react-native';
import { useTheme } from '@/theme';

export type AppTextVariant =
  | 'display'
  | 'title'
  | 'heading'
  | 'body'
  | 'bodyStrong'
  | 'small'
  | 'caption'
  | 'money'
  | 'moneyLarge';

export type AppTextColor =
  | 'textPrimary'
  | 'textSecondary'
  | 'textOnPrimary'
  | 'positive'
  | 'negative'
  | 'warning'
  | 'info';

export interface AppTextProps extends TextProps {
  variant?: AppTextVariant;
  color?: AppTextColor;
  children: React.ReactNode;
  style?: StyleProp<TextStyle>;
}

export function AppText({
  variant = 'body',
  color = 'textPrimary',
  children,
  style,
  ...restProps
}: AppTextProps) {
  const theme = useTheme();

  const colorMap: Record<AppTextColor, string> = {
    textPrimary: theme.colors.textPrimary,
    textSecondary: theme.colors.textSecondary,
    textOnPrimary: theme.colors.textOnPrimary,
    positive: theme.colors.positive.text,
    negative: theme.colors.negative.text,
    warning: theme.colors.warning.text,
    info: theme.colors.info.text,
  };

  const typographyStyle = theme.typography[variant];
  const textColor = colorMap[color];

  return (
    <Text
      style={[
        typographyStyle,
        { color: textColor },
        style,
      ]}
      {...restProps}>
      {children}
    </Text>
  );
}
