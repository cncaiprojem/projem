import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Button } from './Button'
import { ThemeProvider, createTheme } from '@mui/material/styles'

const theme = createTheme()

const renderWithTheme = (component: React.ReactElement) => {
  return render(
    <ThemeProvider theme={theme}>
      {component}
    </ThemeProvider>
  )
}

describe('Button Component', () => {
  it('should render button with text', () => {
    renderWithTheme(<Button>Test Button</Button>)
    
    expect(screen.getByRole('button')).toBeInTheDocument()
    expect(screen.getByText('Test Button')).toBeInTheDocument()
  })
  
  it('should handle click events', () => {
    const handleClick = vi.fn()
    renderWithTheme(<Button onClick={handleClick}>Click Me</Button>)
    
    const button = screen.getByRole('button')
    fireEvent.click(button)
    
    expect(handleClick).toHaveBeenCalledTimes(1)
  })
  
  it('should show loading state', () => {
    renderWithTheme(<Button loading loadingText="Loading...">Submit</Button>)
    
    expect(screen.getByText('Loading...')).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
  })
  
  it('should be disabled when disabled prop is true', () => {
    renderWithTheme(<Button disabled>Disabled Button</Button>)
    
    expect(screen.getByRole('button')).toBeDisabled()
  })
  
  it('should be disabled when loading', () => {
    renderWithTheme(<Button loading>Submit</Button>)
    
    expect(screen.getByRole('button')).toBeDisabled()
  })
  
  it('should apply variant styles', () => {
    const { rerender } = renderWithTheme(<Button variant="contained">Contained</Button>)
    expect(screen.getByRole('button')).toHaveClass('MuiButton-contained')
    
    rerender(
      <ThemeProvider theme={theme}>
        <Button variant="outlined">Outlined</Button>
      </ThemeProvider>
    )
    expect(screen.getByRole('button')).toHaveClass('MuiButton-outlined')
  })
  
  it('should apply color prop', () => {
    renderWithTheme(<Button color="secondary">Secondary</Button>)
    
    expect(screen.getByRole('button')).toHaveClass('MuiButton-colorSecondary')
  })
})