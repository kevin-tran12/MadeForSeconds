import { render, screen } from '@testing-library/react';
import { Badge } from './Badge';
import { describe, it, expect } from 'vitest';

describe('Badge', () => {
  it('renders children correctly', () => {
    render(<Badge>Test Badge</Badge>);
    expect(screen.getByText('Test Badge')).toBeInTheDocument();
  });

  it('applies primary variant classes', () => {
    const { container } = render(<Badge variant="primary">Primary</Badge>);
    expect(container.firstChild).toHaveClass('bg-badge-primary-surface', 'text-badge-primary');
  });

  it('applies success variant classes', () => {
    const { container } = render(<Badge variant="success">Success</Badge>);
    expect(container.firstChild).toHaveClass('bg-success-surface', 'text-success');
  });

  it('applies custom className', () => {
    const { container } = render(<Badge className="custom-class">Custom</Badge>);
    expect(container.firstChild).toHaveClass('custom-class');
  });
});
