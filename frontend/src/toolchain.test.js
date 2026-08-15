import packageJson from '../package.json';

test('uses Vite without unsupported Create React App overrides', () => {
  expect(packageJson.devDependencies).toHaveProperty('vite');
  expect(packageJson.dependencies).not.toHaveProperty('react-scripts');
  expect(packageJson.overrides || {}).not.toHaveProperty('postcss');
  expect(packageJson.overrides || {}).not.toHaveProperty('webpack-dev-server');
  expect(packageJson.overrides || {}).not.toHaveProperty('@svgr/webpack');
});
