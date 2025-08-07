#!/usr/bin/env python3
"""
Minimal Brady M511 label test with precise formatting
"""

import subprocess
import tempfile

def test_minimal_brady_label():
    """Test Brady M511 with minimal content formatted for small labels"""
    
    # Create minimal label content (1.5" x 0.5" label = ~12 chars wide, 2-3 lines max)
    label_content = "TEST123\n"  # Just one line, 7 chars
    
    print(f"Testing minimal label: '{label_content.strip()}'")
    
    # Try with various CUPS options for small labels
    options = [
        [],  # Default
        ['-o', 'PageSize=Custom1'],  # Custom page size
        ['-o', 'fit-to-page'],  # Scale to fit
        ['-o', 'page-left=0', '-o', 'page-right=0', '-o', 'page-top=0', '-o', 'page-bottom=0'],  # No margins
        ['-o', 'Pagination=False'],  # No pagination
        ['-o', 'cpi=10', '-o', 'lpi=6'],  # Character/line density
    ]
    
    for i, opts in enumerate(options):
        print(f"\n--- Test {i+1}: {' '.join(opts) if opts else 'default'} ---")
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmp_file:
            tmp_file.write(label_content)
            tmp_file.flush()
            
            cmd = ['lp', '-d', 'M511'] + opts + [tmp_file.name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"Command: {' '.join(cmd)}")
            print(f"Result: {result.stdout.strip()}")
            if result.stderr:
                print(f"Error: {result.stderr.strip()}")
        
        import os
        os.unlink(tmp_file.name)
        
        input("Press Enter to continue to next test (check printer)...")

if __name__ == "__main__":
    test_minimal_brady_label()