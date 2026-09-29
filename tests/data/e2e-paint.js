const panel = figma.createRectangle();
panel.name = "panel"; panel.resize(400, 400); panel.x = 600; panel.y = 600;
panel.fills = [{ type: "SOLID", color: { r: 0.2, g: 0.4, b: 0.9 } }];
figma.currentPage.children[0].appendChild(panel);
