import { Button as MuiButton, ButtonProps as MuiButtonProps, CircularProgress } from '@mui/material'
import { forwardRef } from 'react'

export interface ButtonProps extends MuiButtonProps {
  loading?: boolean
  loadingText?: string
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ children, loading, loadingText, disabled, ...props }, ref) => {
    return (
      <MuiButton
        ref={ref}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <>
            <CircularProgress size={16} sx={{ mr: 1 }} />
            {loadingText || children}
          </>
        ) : (
          children
        )}
      </MuiButton>
    )
  }
)

Button.displayName = 'Button'