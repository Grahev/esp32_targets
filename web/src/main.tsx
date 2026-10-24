import { render } from 'preact';
import { connect } from './api';
import { App } from './app';
import { applyTheme } from './screens/Settings';
import './styles.css';

applyTheme();
connect();
render(<App />, document.getElementById('app')!);
