'use client'

import { forwardRef } from 'react'

interface FormFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
  helperText?: string
  required?: boolean
}

const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  ({ label, error, helperText, required = true, className = '', ...props }, ref) => {
    const hasError = !!error
    
    return (
      <div className="space-y-1">
        <label htmlFor={props.id || props.name} className="block text-sm font-medium text-gray-700">
          {label}
          {required && <span className="text-red-500 ml-1">*</span>}
        </label>
        
        <div className="relative">
          <input
            ref={ref}
            className={`
              block w-full px-3 py-2 border rounded-md shadow-sm
              placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-offset-2
              disabled:bg-gray-100 disabled:cursor-not-allowed
              ${hasError
                ? 'border-red-300 text-red-900 placeholder-red-300 focus:ring-red-500 focus:border-red-500'
                : 'border-gray-300 focus:ring-blue-500 focus:border-blue-500'
              }
              ${className}
            `}
            {...props}
          />
          
          {/* Error Icon */}
          {hasError && (
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
              <svg
                className="h-5 w-5 text-red-500"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
          )}
        </div>
        
        {/* Error Message */}
        {hasError && (
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        
        {/* Helper Text */}
        {helperText && !hasError && (
          <p className="text-sm text-gray-500">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)

FormField.displayName = 'FormField'

export default FormField